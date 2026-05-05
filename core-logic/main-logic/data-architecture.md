# Database Architecture Design Guide — v2 (Cost-Optimized)

## LoRa Network Coverage Mapping Platform with ML-Based Coverage Analysis

> **Document purpose.** This is the official database architecture for v1 of the platform. It supersedes the previous draft (referred to here as "v1 doc"). Every decision is traced back to one of two anchors: (a) a principle from *A Philosophy of Software Design* (Ousterhout 2018), or (b) the operating cost discipline mandated by `business-logic.md` §7.3 and §11.2 — the platform is donation/grant funded, must maintain ≥6 months of operating reserves, and cannot afford speculative infrastructure spend.
>
> **Audience.** Engineers implementing the data layer; tech leads reviewing code; SREs setting up ops; new engineers onboarding.
>
> **Relationship to v1 doc.** v1 doc was correct on Ousterhout principles but optimized for *correctness and future-proofing*, not *minimum spend to keep the lights on*. This document keeps everything v1 got right and changes only the parts that conflict with the cost mandate. Section 1 is a diff for reviewers familiar with v1.

---

## Table of Contents

1. What changed from v1 (review this if you read v1)
2. Six core design principles
3. The cost lens — third principle alongside Ousterhout's
4. Architecture overview
5. Four capabilities — the only interface application sees
6. Repository interface — formal definition
7. Implementation stack
8. Schema and DDL per capability
9. Data structures in use
10. Cross-cutting concerns
11. Testing strategy
12. Operations — runbook
13. Cost ledger
14. Evolution boundaries — invariants and triggers
15. Appendix — naming conventions

---

## 1. What Changed from v1

This section exists for reviewers who already read v1. New readers can skip to Section 2 — the rest of this document is self-contained.

### 1.1 Kept unchanged (v1 was right)

These v1 decisions are preserved verbatim:

- The 6 design principles intro.
- `Result[T, E]` for business errors; exceptions only for unexpected failure.
- Frozen dataclasses for every value object.
- Domain types instead of primitives (`GatewayId`, not `int`).
- `Confidence` as a data field on every prediction (not a `degraded_mode` flag).
- `model_version` lives in the S3 key prefix — recalibration auto-invalidates without a CDN purge.
- Quarantine and training are two separate tables (no `quarantined: bool` flag).
- `normalized_text` as a generated column, not application-maintained.
- Lint enforcement of layer boundaries via `import-linter`.
- Application never sees the strings "Postgres", "Redis", "stage_4", "GiST", "BRIN".

### 1.2 Changed (v1 was correct but expensive)

| Area | v1 | v2 | Why |
|---|---|---|---|
| Storage systems | 3 (Postgres + Valkey + S3) | 2 mandatory; Valkey triggered by measurement | One fewer system to back up, monitor, upgrade |
| Capabilities | 5 | 4 (TileService merged into CoverageQuery) | `TileService` was 3 thin wrappers over S3 — Ch. 7 anti-pattern |
| Geocoding cascade | 5 hops including Google by default | 3 hops by default; Google is sponsor-only and explicit | Mirrors business-logic §8.3 directly |
| `tier` parameter in C4 | Leaked business concept | Replaced with `GeocodingDepth` enum | Ch. 5 — information hiding |
| `model_was_fallback: bool` | Boolean flag on `Confidence` | `ConfidenceSource` enum | Ch. 5 + Ch. 10 — three states (PRIMARY/FALLBACK/DEGRADED) without adding flags |
| Audit log | TimescaleDB hypertable, 1 year, every read | Plain table, 90 days, only compliance-required events | ~90% storage reduction; hypertable was over-engineering for low volume |
| Schema `core` (users/projects) | Defined in the doc | Removed (was self-contradicted as out-of-scope in §3) | Ch. 17 — consistency |
| Self-hosted Nominatim | Mandatory from day 1 | Optional; default uses Postgres canonical + VietMap/Goong | Removes one heavy server (≥30 GB RAM for VN OSM extract) |
| Cross-region S3 replication | Default for `models-prod` | Deferred until first compliance demand | Doubles storage cost without measured benefit |
| Daily pg_dump | Default | Weekly logical dump + continuous WAL archive | Daily logical dumps on a hypertable are slow; WAL fills the gap |
| MinIO fallback | Maintained alongside R2 | Removed | Two object stores = two deploys |
| Hashicorp Vault | Default | Env vars from a single secrets file | Vault is its own ops surface |
| Postgres roles | 3 (`readonly`, `app`, `admin`) | 2 (`readonly`, `app`) | Admin actions go through migrations + DBA SSH |
| "Skiplist reserved for future" | Documented | Removed | Speculative; revisit when needed |
| `model_version` in `Prediction` | Public field | Available via separate `prediction_metadata()` for audit-needing callers | Audit is not the common case; keep it off the hot path |

### 1.3 Cost summary

Day-1 monthly run-rate target: **under $100/mo for the entire stack** at v1 scale (≤5,000 MAU, ≤50,000 lookups/day, 1–2 provinces pre-computed).

Section 13 publishes a full cost ledger with explicit upgrade triggers.

---

## 2. Six Core Design Principles

These are unchanged from v1. Every decision in this document traces back to one of six.

**Modules should be deep (Ch. 4).** The data layer exposes a narrow interface (4 capabilities, ~14 methods total), but inside it carries the full complexity of SQL, geospatial, time-series, cache cascade, and stage fallback. Cost (interface) small; benefit (functionality) large.

**Information hiding (Ch. 5).** Database type, index type, schema layout, choice of cache backend, ML stage routing — all implementation details. Application code never sees the strings "Postgres", "Redis", "GiST", "Stage 4" in business logic.

**Pull complexity downwards (Ch. 8).** Geocoding cascade, ML stage fallback, retry logic, version mismatch handling, tile-vs-inference routing — all live inside the data layer. The application does not manage them.

**Different layer, different abstraction (Ch. 7).** Application speaks the language of the business domain ("predict at this point"). Repository speaks the language of data access ("query coverage"). Storage speaks SQL.

**Define errors out of existence (Ch. 10).** `Result[T, E]` for business errors. `Confidence` instead of a degraded-mode flag. Empty list instead of "not found". Quarantine separate table instead of a state column.

**Code should be obvious (Ch. 18).** Every method, schema, and constraint has a clear name and a clear reason. A new engineer should understand *why* in hours, not weeks.

---

## 3. The Cost Lens

Ousterhout's principles minimize *cognitive complexity*. For this project, we add a third lens that runs alongside them: **operational cost discipline**, mandated by the donation-funded model.

Every architecture decision must answer three questions, in order:

1. **Does it satisfy the principle?** (Ousterhout)
2. **What does it cost per month at v1 scale?** (cost lens)
3. **Can we defer it until measured demand justifies it?** (cost lens)

A capability that needs an expensive piece of infrastructure on day 1 must justify why deferring it would break the flywheel (business-logic §2). Otherwise: defer.

### 3.1 Hard cost rules

These are non-negotiable, mirroring `business-logic.md` §13.2:

1. **No infrastructure that costs > $50/month on day 1 without a named sponsor or measured demand.**
2. **General donations never pay for Google APIs.** Google is reachable only when a sponsor account is configured for the relevant tier.
3. **Single region until measured load demands more.** No preemptive multi-region anything.
4. **Free tier of every paid service before paid tier.** Cloudflare R2 free egress, Grafana Cloud free monitoring, etc.
5. **Defer the second instance of anything until the first is proven to be the bottleneck.** No replicas, no clusters, no failover targets at v1.

### 3.2 The three-system test

Every time a new external system is proposed (a queue, a search engine, a cache, a CDN, an APM), the proposer must answer:

- What workload makes this necessary?
- How was that workload measured? (If "we expect" — defer.)
- What does it cost monthly?
- Who pays the on-call burden?

Failing any of these answers → not deployed at v1.

---

## 4. Architecture Overview

```
┌────────────────────────────────────────────────────────────┐
│  APPLICATION LAYER                                         │
│  Domain types, business logic, API handlers                │
│  Speaks: Coordinates, Prediction, Project, Tier            │
└────────────────────────────────────────────────────────────┘
                           ↑↓
┌────────────────────────────────────────────────────────────┐
│  REPOSITORY LAYER  (4 capabilities — Section 5)            │
│  CoverageQuery │ SurveyIngest │ GatewayDirectory │         │
│  AddressResolution                                         │
│                                                            │
│  Speaks: data-access methods.                              │
│  Hides: SQL, cascade, version coupling, stage fallback.    │
└────────────────────────────────────────────────────────────┘
                           ↑↓
┌────────────────────────────────────────────────────────────┐
│  STORAGE LAYER  (2 systems mandatory)                      │
│                                                            │
│  PostgreSQL 17 + PostGIS 3.5 + TimescaleDB 2.17            │
│       (single instance — primary engine for queryable data)│
│                                                            │
│  S3-compatible — Cloudflare R2 (PMTiles, model artifacts)  │
│                                                            │
│  ─────────── triggered, not deployed at v1: ───────────    │
│  Valkey 8  (deployed when geocoding cache miss > 30%       │
│             sustained for 7 days — see §10.2)              │
└────────────────────────────────────────────────────────────┘
```

Two storage systems by default. Valkey is a *triggered addition*, not a starting choice. The system is engineered to add Valkey without changing the Repository interface — only the geocoding cascade implementation changes.

---

## 5. Four Capabilities — The Only Interface Application Sees

The application has exactly **four** capabilities from the data layer. No more.

| # | Capability | Purpose | Primary callers |
|---|---|---|---|
| C1 | **CoverageQuery** | Coverage prediction; tile fetch | F1 map, F2 lookup, F3 API |
| C2 | **SurveyIngest** | Receive RSSI/SNR logs | F3 `/survey/upload` |
| C3 | **GatewayDirectory** | Query and manage gateway metadata | F1 map, ML serving |
| C4 | **AddressResolution** | Address ↔ coordinates | F2 lookup |

Important observations:

- **`fetch_tile` lives inside `CoverageQuery`**, not in a separate service. A tile is a pre-computed spatial query result; wrapping S3 in a separate "TileService" creates a shallow pass-through interface (Ch. 7 anti-pattern). Routing between cached tiles and on-demand inference is the actual interesting decision and belongs to one capability.
- **"Geocoding cache" is not a separate capability** — it is an implementation detail of C4.
- **"Model artifact storage" is not a separate capability** — implementation detail of C1.
- **Device last-seen, user/auth/billing** are out of scope for this document. They belong to other services with their own data layers.

This is the application of information hiding (Ch. 5): things that don't need to appear at higher tiers don't appear.

---

## 6. Repository Interface — Formal Definition

This is the most important section. Engineers implementing capabilities must follow this interface strictly. Engineers using capabilities only need to read this section.

### 6.1 Common conventions

**Result type for expected business errors.**

```python
from typing import Generic, TypeVar, Union

T = TypeVar('T')
E = TypeVar('E')

class Ok(Generic[T]):
    value: T

class Err(Generic[E]):
    error: E

Result = Union[Ok[T], Err[E]]
```

Exceptions are reserved for *unexpected* failures (out of memory, connection lost, bugs).

**Frozen dataclasses for every value object.** Structural equality, threadsafe, easily cacheable.

**Domain types instead of primitives.** `GatewayId`, not `int`. `Coordinates`, not `tuple[float, float]`.

### 6.2 Capability C1 — CoverageQuery

```python
class CoverageQuery:
    """Returns coverage prediction for a point, polygon, or tile.

    Internally: routes between pre-computed tiles (fast path)
    and on-demand inference (for hypothetical scenarios).
    Auto-fallbacks Stage 4 → 3 → 2 → 1 if a higher stage is not
    available for that region. Application doesn't need to know
    which stage."""

    def predict(
        self,
        target: Coordinates,
        spreading_factor: SpreadingFactor = SpreadingFactor.SF7,
    ) -> Result[Prediction, PredictionUnavailable]:
        """Single-point prediction. P95 < 200ms from cache."""

    def predict_polygon(
        self,
        boundary: Polygon,
        spreading_factor: SpreadingFactor = SpreadingFactor.SF7,
        resolution_m: Optional[int] = None,
    ) -> Result[CoverageGrid, PredictionUnavailable]:
        """Predict over an area. resolution_m=None → repository
        chooses based on polygon size."""

    def simulate_with_gateway(
        self,
        target: Union[Coordinates, Polygon],
        hypothetical: GatewaySpec,
        spreading_factor: SpreadingFactor = SpreadingFactor.SF7,
    ) -> Result[Union[Prediction, CoverageGrid], PredictionUnavailable]:
        """Simulate adding a hypothetical gateway. P95 < 5s.
        Triggers on-demand inference; does not read tiles."""

    def fetch_tile(
        self,
        z: int,  # zoom level [0, 18]
        x: int,
        y: int,
        layer: TileLayer = TileLayer.COVERAGE,
        as_url: bool = False,
    ) -> Result[Union[TileResponse, SignedUrl], TileNotAvailable]:
        """Pre-computed tile in PMTiles format.
        as_url=True returns a signed CDN URL (preferred for browsers,
        avoids proxying bytes through the backend)."""
```

```python
@dataclass(frozen=True)
class Prediction:
    rssi_dbm: float
    snr_db: float
    coverage_status: CoverageStatus       # GOOD | MARGINAL | NONE
    serving_gateway_id: GatewayId
    confidence: Confidence

@dataclass(frozen=True)
class Confidence:
    """Every prediction comes with confidence. Encoded as data,
    not as a flag, so callers can render uncertainty, estimate
    SLA risk, or hide it for end-user UIs."""
    epistemic_variance: float    # high → lacking data for this region
    aleatoric_variance: float    # high → inherently variable region
    source: ConfidenceSource     # PRIMARY | FALLBACK | DEGRADED

    @property
    def total_variance(self) -> float: ...

    @property
    def credible_interval_95(self) -> tuple[float, float]: ...

class ConfidenceSource(Enum):
    PRIMARY = "primary"      # served by the expected stage for this region
    FALLBACK = "fallback"    # higher stage unavailable, served by a lower stage
    DEGRADED = "degraded"    # inference infrastructure unhealthy; emergency baseline
```

```python
@dataclass(frozen=True)
class PredictionUnavailable:
    """NOT a runtime error — a valid result.
    UX must handle: show 'no data for this region yet'."""
    reason: UnavailabilityReason
    region_supported: bool
    retry_after_seconds: Optional[int]
```

**Critical design decisions:**

- **No `model_stage` in the interface.** Stage is an implementation detail. When the platform reaches a hypothetical Stage 5, no application line changes.
- **No `model_version` in `Prediction`.** Audit-needing callers use a separate `CoverageQuery.prediction_metadata(prediction_id)` accessor. This keeps the hot-path `Prediction` lean.
- **`predict` and `simulate_with_gateway` are split.** Performance contracts differ by an order of magnitude (<200ms vs <5s). Merging them creates a deceptive interface.
- **`ConfidenceSource` is an enum, not a boolean.** v1's `model_was_fallback: bool` could not express the DEGRADED state. An enum captures three operational realities without adding more fields.

### 6.3 Capability C2 — SurveyIngest

```python
class SurveyIngest:
    """Receives RSSI/SNR logs. Internally: validates schema,
    detects outliers, checks geographic plausibility, applies
    reputation weight, places into quarantine.

    Rule: ingestion does NOT serve directly. Every record passes
    through quarantine. The nightly training cycle merges verified
    data into the training set."""

    def submit(
        self,
        records: list[SurveyRecord],
        uploader: UploaderIdentity,
    ) -> Result[IngestReceipt, IngestRejected]:
        """Accepts a batch, returns a receipt.
        Per-record validation lives inside the data layer."""

    def get_batch_status(
        self,
        batch_id: BatchId,
    ) -> Result[BatchStatus, NotFound]:
        """Check batch status (for async UI feedback)."""
```

```python
@dataclass(frozen=True)
class SurveyRecord:
    timestamp: datetime           # UTC, with timezone
    location: Coordinates
    rssi_dbm: float               # valid range: [-150, -30]
    snr_db: float                 # valid range: [-30, 30]
    gateway_id: Optional[GatewayId]
    device_class: DeviceClass

@dataclass(frozen=True)
class IngestReceipt:
    batch_id: BatchId
    accepted_count: int
    rejected: list[RejectedRecord]    # empty list → all records OK
    estimated_training_inclusion: datetime
```

A batch may have some records rejected (RSSI out of range, implausible location). This is *not* a failure of the entire batch — it is "Mask Exceptions" (Ch. 10): per-record failures become data within the response.

### 6.4 Capability C3 — GatewayDirectory

```python
class GatewayDirectory:
    """Manages gateway metadata. Read-heavy, write-rare."""

    def find(self, criteria: GatewayCriteria) -> list[Gateway]:
        """Find gateways matching criteria.
        Empty list is a valid result — does not raise."""

    def get(self, gateway_id: GatewayId) -> Result[Gateway, NotFound]:
        """Lookup by id."""

    def upsert(self, gateway: Gateway) -> Result[Gateway, ConflictError]:
        """Create or update. Cache invalidation automatic."""
```

```python
@dataclass(frozen=True)
class CenterRadius:
    center: Coordinates
    radius_m: float

@dataclass(frozen=True)
class GatewayCriteria:
    """One criteria object covers all v1 query patterns:
    near a point, within a polygon, by operator, by activity."""
    near: Optional[CenterRadius] = None
    within: Optional[Polygon] = None
    operator: Optional[Operator] = None
    only_active: bool = True
    has_recent_uplink: Optional[bool] = None

@dataclass(frozen=True)
class Gateway:
    id: GatewayId
    operator: Operator
    location: Coordinates
    antenna_height_m: float
    tx_power_dbm: float
    antenna_gain_dbi: float
    is_active: bool
    activated_at: datetime
    last_seen_at: Optional[datetime]
```

**v2 change:** v1 had three separate methods (`find_nearby`, `find_in_polygon`, `filter`). They are folded into a single `find(criteria)`. `GatewayCriteria` is general-purpose and deeper than the special-purpose alternatives (Ch. 6) — adding a new filter dimension does not break any caller.

### 6.5 Capability C4 — AddressResolution

```python
class AddressResolution:
    """Address ↔ coordinates. Tolerates Vietnamese with/without
    diacritics, abbreviations, non-standard inputs.

    Internally: cascade Postgres canonical → providers → (sponsor-
    funded paid). Application does not see this — it controls
    only the resource budget via `depth`."""

    def resolve(
        self,
        address: str,
        depth: GeocodingDepth = GeocodingDepth.CACHE_AND_LOCAL,
        bias_region: Optional[VietnameseRegion] = None,
    ) -> Result[ResolvedAddress, AddressUnresolved]:
        """Address → Coordinates. P95 budget per depth — see §10.2."""

    def reverse(
        self,
        location: Coordinates,
    ) -> Result[Address, ReverseUnresolved]:
        """Coordinates → plain Vietnamese address."""

    def suggest(
        self,
        partial: str,
        limit: int = 5,
    ) -> list[AddressSuggestion]:
        """Autocomplete. Empty list if no suggestions."""
```

```python
class GeocodingDepth(Enum):
    """Resource budget for a single resolution call.
    The application maps user tier → depth at request construction;
    the data layer never knows about tiers."""
    CACHE_ONLY      = "cache_only"        # Postgres canonical only; ~95% hit on warm system
    CACHE_AND_LOCAL = "cache_and_local"   # + self-hosted Nominatim if deployed; default
    INCLUDE_PROVIDERS = "include_providers"  # + VietMap/Goong (small per-call cost)
    INCLUDE_PAID    = "include_paid"      # + Google (sponsor-funded only)

@dataclass(frozen=True)
class ResolvedAddress:
    location: Coordinates
    canonical_text: str
    confidence: float          # [0, 1]
    resolved_via: ResolvedVia  # CACHE | NOMINATIM | VIETMAP | GOONG | GOOGLE | MANUAL

@dataclass(frozen=True)
class AddressUnresolved:
    """NOT a runtime error. UX must handle: map point picker."""
    reason: UnresolvedReason   # AMBIGUOUS | NOT_FOUND | OUT_OF_REGION
    suggestions: list[AddressSuggestion]
```

**v2 change:** v1's `tier: UserTier` parameter leaked a business concept (user tier) into the data layer. v2 replaces it with `depth: GeocodingDepth`, which expresses a *resource budget* — a data-layer concept. The mapping `tier → depth` lives one layer up in the application, where it belongs (Ch. 5).

The data layer enforces the cost rule by construction: there is no way to call `resolve` with `INCLUDE_PAID` unless the calling code explicitly passed it. Free-tier code paths simply never construct that value.

---

## 7. Implementation Stack

### 7.1 PostgreSQL 17 + PostGIS 3.5 + TimescaleDB 2.17

The single engine for all data needing structured query.

**Reasons (carried over from v1):**
- One query language for ~90% of the logic. One hiring skill set.
- Full ACID where it's required (project workspace, gateway directory).
- PostGIS is the OGC Simple Features reference implementation — directly compatible with QGIS/ArcGIS used by P3 government.
- TimescaleDB hypertables for `survey_*` time-series: automatic partitioning, ~10–20× compression, still SQL.
- Free cross-domain JOINs: "RSSI logs from past 7 days within polygon X" is one query.

**Production configuration (v1 scale):**
- `shared_buffers = 25%` of RAM
- `effective_cache_size = 75%` of RAM
- `work_mem = 64MB`
- `wal_level = replica` (enables future PITR; replica not deployed at v1)
- `synchronous_commit = on` for OLTP; `synchronous_commit = off` is set per-session for `ts.*` writes (loss tolerance is high; correctness is enforced by quarantine logic)

**Required extensions:**
- `postgis` (3.5+)
- `postgis_raster` — DEM data
- `timescaledb` (2.17+) — hypertable, only on `ts.*` schema
- `pg_trgm` — Vietnamese fuzzy text
- `unaccent` — diacritic stripping
- `pg_stat_statements` — slow query monitoring

**v2 reduction:** TimescaleDB applies only to `ts.*` (survey logs). The audit log moves back to a plain Postgres table — see §8.4.

### 7.2 S3-compatible Object Storage — Cloudflare R2 only

For immutable blobs served via CDN: PMTiles, model artifacts.

**Why Cloudflare R2:** zero egress fees. Tiles are heavily read; egress is the dominant cost on every other provider.

**v2 reduction:** MinIO fallback removed. Two object stores means two deploy paths and two operator skill sets — neither is justified by measured demand at v1.

**Bucket structure:**
```
tiles-prod/
  v=v17/                          # model_version
    layer=coverage/
      z=10/x=812/y=487.pmtiles
    layer=uncertainty/
      z=10/x=812/y=487.pmtiles

models-prod/
  stage=1/region=mekong/calib=v17/model.bin
  stage=3/region=mekong/calib=v17/cnn.onnx
  stage=4/region=mekong/calib=v17/ensemble/m1.onnx
                                            m2.onnx
                                            ...
```

`model_version` in the key prefix is a v1 decision we keep: recalibration v17 → v18 makes old tiles "disappear" from lookup automatically. No CDN purge, no stale flag, no cleanup job. Define errors out of existence, applied to cache invalidation (Ch. 10).

### 7.3 Valkey 8 — Deployed only when triggered

Not deployed at v1.

**The triggering criterion:** geocoding cache cold-miss ratio sustained above 30% for 7 days, *or* P95 lookup latency drifting above 2s due to address resolution.

Until then, the geocoding cache lives in `address.canonical` (Postgres), 30–50ms slower per cold lookup but well within the 3s end-to-end SLA. When triggered, Valkey is deployed and the cascade implementation in `repository/address_resolution/cascade.py` is updated. The Repository interface does not change.

This deferral saves one full system worth of monthly hosting + ops surface (backup, monitoring, on-call expertise, version upgrades) until measurement justifies it.

**Why Valkey not Redis (when the time comes).** Redis Labs changed Redis 7.4's license to RSAL v2 + SSPL in March 2024, creating long-term legal risk if the platform ever offers SaaS. Valkey is a pure-BSD fork hosted by the Linux Foundation. RESP protocol identical, `redis-py` works unchanged.

---

## 8. Schema and DDL Per Capability

Each capability has its own Postgres schema. Schema = namespace. Easier to migrate, back up, and audit.

### 8.1 Schema `geo` — Gateway directory

```sql
CREATE SCHEMA geo;

CREATE TABLE geo.gateways (
    id BIGSERIAL PRIMARY KEY,
    operator TEXT NOT NULL,
    location GEOMETRY(Point, 4326) NOT NULL,
    antenna_height_m REAL NOT NULL CHECK (antenna_height_m > 0),
    tx_power_dbm REAL NOT NULL,
    antenna_gain_dbi REAL NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    activated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX gateways_location_idx
    ON geo.gateways USING GIST (location);

CREATE INDEX gateways_active_operator_idx
    ON geo.gateways(operator)
    WHERE is_active = true;

CREATE INDEX gateways_recent_uplink_idx
    ON geo.gateways(last_seen_at DESC)
    WHERE is_active = true AND last_seen_at IS NOT NULL;
```

### 8.2 Schema `ts` — Survey log time-series

```sql
CREATE SCHEMA ts;

-- Quarantine table: where ingest first lands.
CREATE TABLE ts.survey_quarantine (
    timestamp TIMESTAMPTZ NOT NULL,
    location GEOMETRY(Point, 4326) NOT NULL,
    rssi_dbm REAL NOT NULL CHECK (rssi_dbm BETWEEN -150 AND -30),
    snr_db REAL NOT NULL CHECK (snr_db BETWEEN -30 AND 30),
    gateway_id BIGINT,
    uploader_id BIGINT NOT NULL,
    reputation_weight REAL NOT NULL DEFAULT 1.0,
    batch_id UUID NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

SELECT create_hypertable(
    'ts.survey_quarantine', 'timestamp',
    chunk_time_interval => INTERVAL '7 days'
);

CREATE INDEX survey_q_timestamp_brin_idx
    ON ts.survey_quarantine USING BRIN (timestamp);
CREATE INDEX survey_q_location_idx
    ON ts.survey_quarantine USING GIST (location);
CREATE INDEX survey_q_batch_idx
    ON ts.survey_quarantine(batch_id);

-- Training table: where the verified data accumulates.
CREATE TABLE ts.survey_training (
    timestamp TIMESTAMPTZ NOT NULL,
    location GEOMETRY(Point, 4326) NOT NULL,
    rssi_dbm REAL NOT NULL,
    snr_db REAL NOT NULL,
    gateway_id BIGINT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    region TEXT NOT NULL  -- denormalized for partition pruning
);

SELECT create_hypertable(
    'ts.survey_training', 'timestamp',
    chunk_time_interval => INTERVAL '30 days'
);

CREATE INDEX survey_t_timestamp_brin_idx
    ON ts.survey_training USING BRIN (timestamp);
CREATE INDEX survey_t_location_idx
    ON ts.survey_training USING GIST (location);
CREATE INDEX survey_t_region_idx
    ON ts.survey_training(region, timestamp DESC);

ALTER TABLE ts.survey_training SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'region',
    timescaledb.compress_orderby = 'timestamp DESC'
);

SELECT add_compression_policy(
    'ts.survey_training',
    INTERVAL '30 days'
);
```

Quarantine and training are two separate tables, not two states on one table. This is "Define special cases out of existence" (Ch. 10) — querying the training set never requires `WHERE quarantined = false`.

### 8.3 Schema `address` — Geocoding canonical

```sql
CREATE SCHEMA address;

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE OR REPLACE FUNCTION address.normalize_vn(input TEXT)
RETURNS TEXT AS $$
BEGIN
    RETURN lower(unaccent(input));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE TABLE address.canonical (
    id BIGSERIAL PRIMARY KEY,
    raw_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL
        GENERATED ALWAYS AS (address.normalize_vn(raw_text)) STORED,
    location GEOMETRY(Point, 4326) NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    resolved_via TEXT NOT NULL CHECK (resolved_via IN (
        'cache','nominatim','vietmap','goong','google','manual'
    )),
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (raw_text)
);

CREATE INDEX canonical_normalized_trgm_idx
    ON address.canonical USING GIN (normalized_text gin_trgm_ops);

CREATE INDEX canonical_location_idx
    ON address.canonical USING GIST (location);
```

`normalized_text` is a generated column. The DBMS guarantees it stays in sync with `raw_text`. Application code cannot accidentally write inconsistent data — information hiding at the DDL level.

This table doubles as the v1 geocoding cache. When Valkey is later triggered, Valkey becomes the hot tier and this table becomes the cold tier. No schema change.

### 8.4 Schema `audit` — Compliance log (simplified)

```sql
CREATE SCHEMA audit;

-- Plain table, no hypertable. v1-scale audit volume does not justify TimescaleDB.
CREATE TABLE audit.compliance_log (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id BIGINT,
    action TEXT NOT NULL,            -- e.g. 'export.geotiff', 'survey.upload'
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX compliance_log_occurred_idx
    ON audit.compliance_log(occurred_at DESC);

CREATE INDEX compliance_log_user_idx
    ON audit.compliance_log(user_id, occurred_at DESC)
    WHERE user_id IS NOT NULL;

-- 90-day retention via daily cron:
-- DELETE FROM audit.compliance_log WHERE occurred_at < NOW() - INTERVAL '90 days';
```

**v2 decisions:**

- **Logged events (only):**
  - Shapefile / GeoTIFF export — required by P3 government compliance.
  - Survey upload — required by ML team for data lineage and contamination debugging.
  - Admin operations on user / api_key.
- **Not logged (v1 logged these; v2 does not):**
  - Every gateway read.
  - Every coverage query.
- **Plain table, not a hypertable.** At v1 scale, expected log volume is single-digit thousands of rows per day. TimescaleDB pays off above ~10M rows.
- **90-day retention via cron DELETE.** No `add_retention_policy` machinery.

This change reduces audit storage by roughly 90% and removes one TimescaleDB consumer from operations.

---

## 9. Data Structures in Use

Background documentation for engineers — explains *why* indexes are chosen this way. Application code does not need this.

### 9.1 B+ tree (Postgres default)

For every scalar column needing equality, range, or `ORDER BY`.
- `geo.gateways(operator)` partial index
- `address.canonical(raw_text)` UNIQUE
- `audit.compliance_log(user_id, occurred_at DESC)`

O(log n) lookup, fast range scans, fits medium write rates.

### 9.2 R-tree (via Postgres GiST)

For every geometry/geography column needing spatial query.
- `geo.gateways(location)` — find within radius
- `ts.survey_*(location)` — spatial filter within time windows
- `address.canonical(location)` — reverse geocoding

PostGIS implements an R-tree variant via GiST. OGC-compliant. Bounding box hierarchy supports overlap.

### 9.3 Inverted index (via Postgres GIN)

- `address.canonical(normalized_text)` with `pg_trgm` — fuzzy Vietnamese match.
- (No JSONB GIN at v1 — `core` schema is out of scope.)

Token → posting list. Slow build, fast lookup. Ideal for compound types.

### 9.4 BRIN — Block Range Index

- `ts.survey_quarantine(timestamp)`
- `ts.survey_training(timestamp)`

Append-only tables naturally sorted by timestamp. BRIN stores min/max per 8KB block — index size <0.1% of B-tree. The difference between a few MB and tens of GB at billion-row scale.

### 9.5 Object key prefix (S3)

For tile and model artifact lookup.
- Format: `{layer}/v={version}/z={z}/x={x}/y={y}.pmtiles`
- Not an index in the B-tree sense; S3 prefix lookup is effectively O(1) for an exact key.

### 9.6 Summary

| Column / Use case | Index / Structure | Reason |
|---|---|---|
| `gateways(location)` | GiST (R-tree) | Standard spatial; OGC-compliant |
| `gateways(operator)` partial | B-tree | Fast filtering of active gateways |
| `survey_*(timestamp)` | BRIN | Append-only; billion-row scale |
| `survey_*(location)` | GiST | Spatial filter within time window |
| `canonical(normalized_text)` | GIN + pg_trgm | Vietnamese fuzzy match with/without diacritics |
| `canonical(location)` | GiST | Reverse geocoding |
| `compliance_log(user_id, occurred_at)` | B-tree | User audit trail |
| Tile lookup | S3 key prefix | Object storage; CDN edge cache |

---

## 10. Cross-Cutting Concerns

### 10.1 Stage version coupling (Stage 1 ↔ Stage 2/3/4)

Per `core-feature.md` §1.5.1, each residual learner trains on targets derived from the Stage 1 baseline. Recalibrating Stage 1 invalidates downstream.

**Implementation:**
- Each model artifact key on S3 contains the Stage 1 calibration version: `models/stage3/region=mekong/calib=v17/model.bin`.
- The internal `model_router.best_for(location)` returns only models whose `calib_version` matches the current Stage 1.
- When Stage 1 recalibrates v17 → v18, old model files don't match the router's filter — they "disappear" from production. No deletion needed, no stale flags. The router auto-falls back to Stage 1 for that region.
- A background job retrains downstream stages with calib v18 within 7 days.

"Stale model" is not a state — it is "no matching file". Define error out of existence (Ch. 10).

### 10.2 Geocoding cascade

The cascade lives in `repository/address_resolution/cascade.py`. Application does not see it.

```
resolve(address, depth=CACHE_AND_LOCAL):

  step 1: Postgres canonical (always)
            P95 < 50ms; ~95% hit on warm system

  step 2: depth ≥ CACHE_AND_LOCAL:
            self-hosted Nominatim if deployed,
            else skip
            P95 < 300ms

  step 3: depth ≥ INCLUDE_PROVIDERS:
            VietMap or Goong (domestic, low cost)
            P95 < 800ms

  step 4: depth == INCLUDE_PAID:
            Google Maps Geocoding
            ONLY if a sponsor account is configured
            P95 < 1500ms

  → Result.Ok | AddressUnresolved with suggestions
```

Every successful resolution at step 2+ writes back to step 1 (Postgres canonical). This is how the system learns Vietnamese addresses over time.

**v2 cost rule, enforced in code:** when `INCLUDE_PAID` is requested but no Google sponsor account is configured, the cascade returns `AddressUnresolved` with `reason=PAID_PROVIDER_UNAVAILABLE` rather than failing open or charging the general donation pool. Mirrors business-logic §8.3.

### 10.3 Monitoring and alerting (essential metrics only)

Every capability emits metrics to Prometheus. Application doesn't publish; Repository does.

**Tracked at v1:**
- `{capability}_request_duration_seconds` histogram, by method
- `{capability}_request_total` counter, by method × status
- `coverage_query_stage_fallback_total` counter — increments whenever served stage < expected stage
- Postgres disk usage, R2 monthly bandwidth, Postgres connection pool utilization
- Stage 4 ECE rolling 7-day (auto-rollback trigger)

**Not tracked at v1:** geocoding cache hit ratio (Valkey not deployed; cache hit is on the Postgres path and visible via `pg_stat_statements`).

**Alert thresholds:**
- C4 `resolve` P95 > 2s for 5 minutes → page on-call.
- C1 `predict` P95 > 500ms for 5 minutes → warning.
- Any capability error rate > 1% for 5 minutes → page.
- Stage 4 ECE rolling 7-day > 0.08 → auto-rollback to Stage 3 + alert.
- Postgres disk > 70% → warning; > 85% → page.

**Hosting:** Grafana Cloud free tier (10k series, 14-day retention) covers v1 monitoring needs. No self-hosted Prometheus stack at v1.

### 10.4 Schema migration

**Tool:** Alembic. Each migration in `migrations/YYYYMMDDHHMM_<slug>.py` with both `upgrade()` and `downgrade()`.

**Safe (migration only):**
- Add new column with default.
- Add new index.
- Add new table within an existing schema.
- Rename column with a wrapping view.

**Requires Repository coordination:**
- Restructure tables.
- Change index type.
- Rename schema.

**Requires ADR + Repository major version bump:**
- Change a field in a public dataclass (Section 6).
- Change an enum value of a public type.
- Change semantic of a method.

**Zero-downtime rule:** never drop a column in production until new code has run stably for ≥7 days. Drop columns in a separate migration after verifying no code references remain.

### 10.5 Security and access control

**Postgres roles (two only):**

```sql
CREATE ROLE readonly_role;
CREATE ROLE app_role;

GRANT USAGE ON SCHEMA geo, ts, address TO app_role;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA geo, ts, address TO app_role;
GRANT USAGE, SELECT ON ALL SEQUENCES
    IN SCHEMA geo, ts, address TO app_role;

GRANT USAGE ON SCHEMA geo, ts, address, audit TO readonly_role;
GRANT SELECT ON ALL TABLES
    IN SCHEMA geo, ts, address, audit TO readonly_role;
```

Admin operations (creating users, dropping tables, role grants) go through migrations or DBA SSH. No separate admin role to maintain.

**API secrets:** loaded from a single environment file at process start. Repository receives a config object — it does not know the source. When a sponsor secret manager is required (e.g., Cloudflare-funded Workers), the loader implementation changes; Repository signature does not.

**Audit-required events** are listed in §8.4. Audit hits the `audit.compliance_log` table directly via a small writer in `infrastructure/audit_writer.py`. No buffering, no async — keep it boring.

---

## 11. Testing Strategy

Tests facilitate refactoring (Ch. 19). Without them, you cannot confidently change anything.

### 11.1 Pyramid

- Unit: ~70%. Pure logic — validators, model_router, cascade.
- Integration: ~25%. Real Postgres via testcontainers.
- End-to-end: ~5%. HTTP → repository contract verification.

### 11.2 Unit example

```python
def test_rejects_rssi_out_of_range():
    record = SurveyRecord(
        timestamp=datetime.now(timezone.utc),
        location=Coordinates(16.07, 108.22),
        rssi_dbm=-200,           # invalid
        snr_db=10,
        gateway_id=None,
        device_class=DeviceClass.STANDARD,
    )
    result = validate_record(record)
    assert isinstance(result, RejectedRecord)
    assert result.reason == RejectReason.RSSI_OUT_OF_RANGE
```

### 11.3 Integration example

```python
@pytest.fixture(scope="module")
def directory(postgres_container):
    return GatewayDirectoryPostgres(postgres_container.dsn)

def test_find_returns_within_radius(directory):
    g = Gateway(...)
    directory.upsert(g)
    result = directory.find(GatewayCriteria(
        near=CenterRadius(Coordinates(16.07, 108.22), 5000),
    ))
    assert len(result) == 1
    assert result[0].id == g.id

def test_find_returns_empty_outside_radius(directory):
    """Empty list is a valid result — does not raise."""
    result = directory.find(GatewayCriteria(
        near=CenterRadius(Coordinates(0, 0), 1000),
    ))
    assert result == []
```

### 11.4 Contract tests

Every implementation of a capability passes the same contract test suite. When Postgres is later supplemented or replaced (e.g., ClickHouse for survey logs at extreme scale), the same tests must pass.

```python
class CoverageQueryContractTests:
    @pytest.fixture
    def query(self) -> CoverageQuery:
        raise NotImplementedError("subclass provides")

    def test_predict_returns_result_type(self, query):
        result = query.predict(Coordinates(16.07, 108.22))
        assert isinstance(result, (Ok, Err))

    def test_confidence_always_populated_on_success(self, query):
        result = query.predict(Coordinates(16.07, 108.22))
        if isinstance(result, Ok):
            assert result.value.confidence is not None
```

### 11.5 Linting

Architecture enforced via `import-linter`:

```toml
[importlinter:contract:layered]
type = layers
layers =
    application
    repository
    infrastructure
    domain

[importlinter:contract:no-cross-capability]
type = independence
modules =
    repository.coverage_query
    repository.survey_ingest
    repository.gateway_directory
    repository.address_resolution
```

CI fails on violation. Information hiding enforced at the build pipeline.

---

## 12. Operations — Runbook

### 12.1 Backup

**Postgres:**
- Continuous WAL archiving to R2 (enables PITR).
- **Weekly** logical `pg_dump` for `geo` and `address` schemas (small; fast recovery).
  v1 doc said daily — but `ts.*` is a hypertable and a daily logical dump is slow and expensive. WAL covers the gap; weekly is enough.
- Restore drill: quarterly, measure RTO/RPO. Document in the wiki.

**Object storage (R2):**
- Bucket versioning **on for `models-prod` only** (model artifact recovery is more valuable than tile recovery; tiles are recomputable from inputs).
- **No cross-region replication at v1.** Trigger condition: first compliance demand or first paid SLA.

### 12.2 Capacity planning

**Postgres:**
- Monitor `pg_database_size()` weekly. Alert at 70% disk.
- Watch `ts.survey_*` chunk count (the fastest-growing tables). Compress chunks older than 30 days for ~10–20× storage saving.
- Track connection pool utilization; v1 budget = 50 connections. Above 80% sustained → tune pool or investigate leaks before raising the limit.

**R2:**
- Monthly egress dashboard. R2 free egress is large but not infinite — if traffic ever forces a paid plan, that itself is a milestone worth investigating.

### 12.3 On-call playbook

**Symptom: lookup P95 > 3s.**
1. Open Grafana "Lookup latency breakdown".
2. Geocoding > 1.5s → Postgres `address.canonical` slow. Check `pg_stat_statements`. Likely fix: deploy Valkey (per §10.2 trigger).
3. Inference > 1s → ML serving slow. Check ML serving health.
4. Both healthy but P95 high → Postgres connection pool near limit. Check `pg_stat_activity`.

**Symptom: Stage 4 ECE > 0.08.**
1. Confirm auto-rollback fired (check `model_router` log).
2. If yes: Stage 3 is serving. Open ticket — ML team retrains within 7 days.
3. If no: trigger rollback manually via the admin endpoint. File an alerting bug.

**Symptom: Postgres disk > 85%.**
1. `\dt+` to find largest tables. Almost always `ts.survey_*`.
2. Confirm compression policy is active for chunks older than 30 days.
3. If compression active and disk still rising — schedule an upgrade of the Postgres instance disk.
4. If the platform is approaching multiple TB of survey data, this is the trigger for the W3 → ClickHouse migration described in §14.3.

**Symptom: connection pool exhausted.**
1. `pg_stat_activity` for long-running queries. Kill anything > 5 minutes that is not a migration.
2. Audit the most recent Repository deploy: any unclosed transactions?
3. Temporarily raise pool size by 50% as bridge until the root cause is identified.

---

## 13. Cost Ledger

A new section for v2. Tracks the *expected* monthly cost per piece of infrastructure for honesty and for transparent reporting (`business-logic.md` §7.3 requires public quarterly financial transparency).

### 13.1 Day-1 expected monthly run-rate

At v1 scale: ≤5,000 MAU, ≤50,000 lookups/day, 1–2 provinces pre-computed.

| Component | Day 1 cost | Notes |
|---|---|---|
| Postgres (single VPS, 4 vCPU, 16 GB RAM, 200 GB SSD) | ~$30–50/mo | Hetzner, Contabo, or similar EU/SG VPS. Self-managed. |
| Cloudflare R2 storage (10 GB, free tier) | $0 | Free tier |
| Cloudflare R2 egress | $0 | Egress is free on R2 |
| Grafana Cloud (free tier) | $0 | 10k series, 14-day retention |
| Cron job runner / scheduler | $0 | systemd timers on the Postgres VPS |
| Self-hosted Nominatim | $0 | Not deployed at v1 |
| Valkey | $0 | Not deployed at v1 |
| Domain + TLS (Let's Encrypt) | ~$1/mo | Domain only |
| **Subtotal** | **~$30–50/mo** | |

ML serving infrastructure (model artifact serving, GPU when Stage 3+ is reached) is tracked in a parallel ML-ops budget — not part of this data layer.

### 13.2 Upgrade triggers and their cost impact

| Component | Trigger to deploy | Added monthly cost |
|---|---|---|
| Postgres read replica | OLAP queries impacting OLTP P95 | +$30–50/mo (mirror VPS) |
| Valkey | Geocoding cache miss > 30% for 7 days | +$15–25/mo (small VPS) |
| Self-hosted Nominatim | VietMap/Goong cost > $30/mo or hit ratio low | +$30–50/mo (large RAM VPS) |
| Cross-region R2 replication | First compliance / paid-SLA demand | Doubles R2 storage cost |
| Sentry / paid APM | Volume exceeds Grafana free tier | +$20–50/mo |
| ClickHouse for survey logs | All three conditions in §14.3 | +$50+/mo + ops complexity |
| Google geocoding | Sponsor-funded only | $0 to platform; sponsor pays |

### 13.3 Discipline

- This table is the single source of truth for "what does it cost to keep this running this month."
- Updated by SRE quarterly and published in the donation transparency report.
- Any line item rising > 20% quarter-over-quarter triggers an investigation.
- Total monthly run-rate must stay under ~30% of the trailing-3-month donation inflow average. If it exceeds that ratio, the response is *cut a component*, not raise donations.

---

## 14. Evolution Boundaries — Invariants and Triggers

The system will evolve. This section defines what *may not* change without an ADR (invariants) and what *should* change under specific measured conditions (triggers).

### 14.1 Hard invariants (breaking these breaks the architecture)

1. Application never imports from `infrastructure/`.
2. Application never sees the strings `postgres`, `redis`, `valkey`, `s3`, `stage_4`, `GiST`, `BRIN` in business code.
3. Every successful prediction comes with `Confidence`. A `Prediction` without confidence cannot exist.
4. Every survey upload passes through quarantine first. No "trusted uploader bypass" — reputation expresses trust as weight, never as a shortcut.
5. General donation funds never reach Google. Enforced inside the cascade, not in the application.
6. Model artifact keys contain calibration version. Recalibration never breaks downstream by deleting files.
7. The audit log records every Shapefile/GeoTIFF export.

### 14.2 What may change without an ADR

- Index types per schema (e.g., switch a B-tree to a hash index after measurement).
- Postgres configuration (`work_mem`, `shared_buffers`, etc.).
- Geocoding provider implementations (replace VietMap module with another — only that file changes).
- Cache TTL for `address.canonical`.
- CDN provider (R2 → other), as long as S3 API compatibility is preserved.

### 14.3 Triggered evolutions (require measurement, not opinion)

**Deploy Valkey:**
- Geocoding cache cold-miss > 30% sustained for 7 days, OR
- Lookup P95 drifts above 2s with `address.canonical` identified as the dominant component.

**Deploy self-hosted Nominatim:**
- VietMap/Goong combined monthly cost > $30, OR
- Cache hit ratio drops below 70%.

**Move survey logs to ClickHouse:**
- All three conditions, all simultaneous:
  - `ts.survey_training` exceeds 10 billion rows.
  - Analytical queries (aggregation by region/month) > 30% of the workload.
  - Postgres P95 for analytical queries > 30s.
- Migration: replace `SurveyIngest.postgres_impl` with `clickhouse_impl`. Repository interface unchanged. Application unaware.

**Split Repository into a microservice:**
- The capability count exceeds 10, AND
- The Repository-owning team exceeds 5 engineers, AND
- Cross-team coordination overhead exceeds the network overhead a microservice split would introduce.
- Migration: the Section 6 interface becomes a gRPC contract. Method signatures unchanged. Application moves from in-process call to RPC.

### 14.4 ADR process

Anything beyond §14.2 requires an Architecture Decision Record:

- File: `docs/adr/NNNN-<slug>.md`
- Format: Context → Decision → Consequences → Alternatives considered.
- Cost lens is part of every ADR: include the expected monthly cost delta.
- Review by ≥2 senior engineers.
- Merge ADR first, implement second.

---

## 15. Appendix — Naming Conventions

Names should be precise (Ch. 14). Consistent names reduce cognitive load.

### 15.1 Database objects

- Schema: lowercase, singular noun. `geo`, `ts`, `address`, `audit`.
- Table: lowercase, snake_case, plural noun. `gateways`, `survey_quarantine`.
- Column: lowercase, snake_case. `gateway_id`, `received_at`.
- Index: `<table>_<columns>_<type>_idx`. Example: `gateways_location_idx`, `survey_q_timestamp_brin_idx`.
- Constraint: `<table>_<column>_check` for CHECK; `<table>_<column>_fk` for FK.
- Foreign key column: `<referenced_table_singular>_id`. Example: `gateway_id` references `gateways.id`.

### 15.2 Python code

- Class: PascalCase. `GatewayDirectory`, `Coordinates`, `Prediction`.
- Function/method: snake_case. `find`, `predict`.
- Constant: UPPER_SNAKE_CASE. `MAX_BATCH_SIZE`, `DEFAULT_RADIUS_M`.
- Domain types: descriptive suffix. `GatewayId` (not `Gateway`), `BatchId`, `ModelVersion`.

### 15.3 IDs

- Database PK: `BIGSERIAL` for most. `UUID v7` for `batch_id` (sortable by time + globally unique).
- Application: wrap PK in a domain type. `gateway_id: GatewayId`, never `gateway_id: int`.

### 15.4 Time

- Every timestamp in DB: `TIMESTAMPTZ` (with timezone). Stored as UTC.
- Application uses `datetime` with `tzinfo` set. Never naive.
- Time column names: `<verb>_at`. `created_at`, `received_at`, `activated_at`. Not `created`, `creation_time`.

### 15.5 Boolean

- Column: `is_<adjective>` or `has_<noun>`. `is_active`, `has_recent_uplink`.
- Avoid negative naming: `is_active`, not `is_inactive`.

### 15.6 Versioning

- Model calibration version: `v<n>`. (`v17`, `v18`.)
- Schema migration: `YYYYMMDDHHMM_<verb>_<object>.py`. Example: `202602051430_add_index_to_gateways.py`.
- Tile path version: in S3 key prefix, synced with model calibration version.

---

*End of design guide.*