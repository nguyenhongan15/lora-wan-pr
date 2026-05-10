# System Design Document

## LoRa Network Coverage Mapping Platform with ML-Based Coverage Analysis

> **Document purpose.** This is a consolidated system design report covering the strategic, functional, and technical architecture of the platform. It synthesizes four source specifications — customer needs (`customer-analysis.md`), business logic (`business-logic.md`), core features (`core-feature.md`), and data architecture (`data-architecture.md`) — into a single narrative suitable for engineering leads, funders, grant reviewers, and academic supervisors.
>
> **Audience.** Mixed: engineering, product, business, and academic readers.
>
> **Design philosophy.** Every architectural decision in this document traces back to one of two anchors: a principle from *A Philosophy of Software Design* (Ousterhout, 2018), or the operating-cost discipline mandated by the donation-funded business model.

---

## Table of Contents

1. Executive Summary
2. Goals, Constraints, and Non-Negotiables
3. Stakeholders and User Segments
4. Core Features — The Three-Feature Flywheel
5. System Architecture
6. Data Architecture
7. Machine Learning Model Architecture
8. API and Output Format Design
9. Non-Functional Requirements
10. Operational Design
11. Risk Management
12. Evolution Roadmap and Success Metrics
13. Appendix — Quick Reference

---

## 1. Executive Summary

The platform delivers one fundamental capability — *predicting LoRa network coverage where no one has measured it* — packaged across three feature surfaces that together form a self-reinforcing data and product flywheel. It is positioned for the Vietnamese IoT market and serves seven customer segments with deliberately uneven priority.

The platform is **fully free at every access level**. Sustainability comes from donations, community contributions, grants, sponsorships, and open-source development — not from paid tiers. User groups are differentiated by *use case* (individual, academic, professional, enterprise, OEM), not by payment.

The system rests on three coupled bets:

1. **Technical bet.** ML can predict coverage accurately enough that organizations adopt the platform for real planning decisions, not as a curiosity. One km² of drive testing costs millions of VND; an 85% accurate model across a national expansion saves billions of VND.
2. **Distribution bet.** A free, fast, shareable address-lookup feature produces sustained adoption volume across all user groups at zero marginal cost, feeding both data ingestion and community visibility.
3. **Ecosystem bet.** Once an API is integrated into a user's internal systems and survey upload becomes part of their workflow, the platform becomes the de-facto Vietnamese LoRa standard — a position more durable than commercial lock-in because it is reinforced by every contribution back to the model.

Removing any one of the three breaks the loop. **The three core features are non-negotiable as a set.**

---

## 2. Goals, Constraints, and Non-Negotiables

### 2.1 Primary goals

The platform must (a) predict coverage in unmeasured areas with quantified uncertainty, (b) acquire users at near-zero marginal cost through a viral lookup surface, and (c) ingest contributed RSSI logs back into model training so the system improves over time without commercial lock-in.

### 2.2 Hard constraints

- **End-to-end lookup latency P95 < 3 seconds.** Operating SLA, not a target.
- **API point query P95 < 500 ms; map tile delivery P95 < 1 second from cache.**
- **Predictions for Professional tier and above must include uncertainty.**
- **General donation funds never pay for Google APIs.** Google is reachable only when a sponsor account is configured for the relevant tier.
- **Day-1 monthly run-rate target: under USD 100/month** for the entire data-layer stack at v1 scale (≤5,000 MAU, ≤50,000 lookups/day, 1–2 provinces pre-computed).
- **Maintain at least 6 months of operating reserves** before expanding feature scope.

### 2.3 Non-negotiable principles

1. **The flywheel is indivisible.** When budget must be cut, ship v0.1 of all three features rather than v1.0 of one or two.
2. **Predictions without uncertainty are not products.** The line between toy and engineering instrument is uncertainty visualization.
3. **ML stages are never retired.** Each stage adoption is a permanent operational commitment.
4. **No private features.** Every feature is free and open-source; sponsorship buys logo placement and roadmap priority — never private capability.
5. **Public financial transparency.** Quarterly reports are a survival condition of the donation model.

---

## 3. Stakeholders and User Segments

Seven personas are defined. Priority is *not* a function of total addressable market — it is a function of **data flywheel contribution × adoption volume × ecosystem leverage**.

### 3.1 Persona priority matrix

| Priority | Personas | Rationale |
|---|---|---|
| **High** | P1 IoT Solution Companies | Active strategic question (rent vs build a private LoRa network); highest-quality survey uploads. |
| **High** | P2 Telecom / Network Operators | Largest infrastructure; substantial budget; replaces drive-testing cost. |
| **High** | P5 End Users (farmers, small fleet operators) | Funnel volume; viral sharing through shareable links and Open Graph cards. |
| **Medium** | P4 Researchers and Engineering Students | Open-source code, benchmarks, survey data; 3–5 year talent pipeline into P1/P2. |
| **Medium** | P6 Hardware Vendors | Embedded widget on their store delivers traffic at zero CAC. |
| **Medium** | P7 System Integrators | Channel multiplier into end-customer projects; survey uploads from field surveys. |
| **Low** | P3 Smart City / Government | Long B2G procurement cycles; treat as funding opportunity (grants, commissioned deployments), not a strategic spine. |

### 3.2 Feature value mapping

| Persona | F1 ML Map | F2 Lookup | F3 API |
|---|---|---|---|
| P1 IoT Solution Cos | **Critical** — feasibility & cost decisions | Used informally before sales call | **Critical** — embed coverage layer |
| P2 Telecom Operators | **Critical** — replaces drive testing | Low | High — bulk planning workflows |
| P3 Government | High — provincial overview reports | Low | Medium — GIS integration |
| P4 Researchers | Medium — model benchmarking | Low | **Critical** — raw data export |
| P5 End Users | Low — abstracted away | **Critical** — the only surface they see | None |
| P6 Hardware Vendors | Low | **Critical** — embeddable widget | Medium — compatibility matrix |
| P7 System Integrators | High — pre-sales artifacts | Used during site visits via mobile | **Critical** — survey upload, BoM automation |

### 3.3 Use-case tier structure (all free)

Tiering is not a monetization mechanism. It exists to plan infrastructure, grant deeper access to committed contributors, and shape UX to the use case.

| Tier | Target | Features unlocked | Unlock requirement |
|---|---|---|---|
| **Community** | P5, casual P1, evaluating engineers, all new users | Single-point lookup, basic web map, basic mobile app, deep-link & widget viewing | None — no signup |
| **Academic / Research** | P4 | + Raw data export, sandbox for user models, classical-model comparison, generous API rate limits | Academic email or letter |
| **Professional / SI** | P7, small P1 | + Site survey mode, bulk CSV, BoM generation, project workspace, white-label reports | Account + work email |
| **Enterprise / Operator** | Large P1, P2, some P3 | + Full API + SDK, webhooks, optimization endpoint, multi-tenant SLA, multi-operator comparison | Intake process + soft commitment to upload survey data |
| **OEM / Partner** | P6 | + White-label widget, custom branding, compatibility-matrix listing, deep-link tracking | Partner agreement (no fee) |

---

## 4. Core Features — The Three-Feature Flywheel

The three features are not independent. Each reinforces the next.

```
   Free lookup (CAC ≈ 0)
           │ attracts users
           ▼
   ML map with uncertainty
           │ proves credibility, converts users into committed participants
           ▼
   API integration + survey upload
           │ deepens integration and ingests contributed data
           ▼
   Better model → Better map → Better lookup accuracy → Wider adoption
           ↺ loop
```

### 4.1 Feature 1 — ML-based Coverage Map

**Strategic role.** Technical credibility. The proof artifact that converts curious users into committed participants.

**Inputs.** Gateway metadata (location, antenna height, Tx power, gain, pattern); Digital Elevation Model (SRTM 30 m baseline, MONRE 5 m where available); land cover (OpenStreetMap, Microsoft Building Footprints, Sentinel-2 NDVI); ground-truth RSSI/SNR logs; end-device parameters (Spreading Factor SF7–SF12).

**Outputs.** A 100 m × 100 m raster coverage layer (configurable). Per-pixel: predicted RSSI (dBm), predicted SNR (dB), serving gateway, link-budget margin. A separate uncertainty layer rendered visually distinct (transparency, hatching, or a secondary color channel). A categorical Good / Marginal / No-Coverage overlay for non-technical users.

**Core operating rule.** Predicted coverage must always be paired with visible uncertainty. A region predicted "well covered" with 50% confidence must be visually distinguishable from one predicted "well covered" with 95% confidence. Rendering predictions without uncertainty is the dividing line between a toy and an engineering instrument.

**Performance rule.** Per-province pre-computed tiles in PMTiles/MBTiles served via CDN. Real-time inference is reserved exclusively for "what-if" scenarios when a user drags a hypothetical gateway. This is the only architecture that scales to multiple provinces without a GPU bill that breaks operating economics.

**User-configurable inputs.** Spreading Factor (SF7–SF12) — SF12 reaches 4–5× further than SF7 — and hypothetical gateway placement scenarios.

### 4.2 Feature 2 — Address and Coordinate Lookup

**Strategic role.** Acquisition funnel. Every persona, including senior engineers at P2, passes through this entry point.

**Hard latency budget: < 3 s P95 end-to-end**, including geocoding, model inference, and rendering. This is an operating-level SLA, not a technical preference. A lookup taking longer breaks fluency and significantly reduces conversion.

**Two-layer output.** Every lookup returns simultaneously:

- **Layer 1 (default).** 🟢 / 🟡 / 🔴 status, one-sentence Vietnamese explanation, map snapshot.
- **Layer 2 (revealed on click).** RSSI in dBm, SNR in dB, recommended SF, nearest serving gateway with link, confidence score.

This dual-layer logic is what allows a single feature to serve P5 and a P2 senior engineer in the same session.

**Input formats.** Vietnamese addresses with and without diacritics ("Đà Nẵng" and "Da Nang" both resolve); colloquial / non-standard inputs with graceful fallback to manual map selection; decimal and DMS coordinates; direct map tap; current GPS; bulk CSV upload.

**Virality mechanisms (must be built).** Shareable deep links of the form `app.com/check?lat=16.07&lng=108.22`; auto-generated Open Graph cards for Facebook and Zalo previews; embeddable widget for hardware-vendor sites.

### 4.3 Feature 3 — API and Data Export

**Strategic role.** Both retention anchor and data ingestion pipeline.

**The bidirectional rule.** The API is not just read endpoints. `POST /survey/upload` accepts user-contributed RSSI logs, each becoming a training sample. Every API user is also a data contributor — the mechanism by which the platform's model improves over time while competitors' do not.

**Minimum endpoint specification.**

| Endpoint | Purpose |
|---|---|
| `GET /coverage/point` | Single-point coverage check |
| `POST /coverage/batch` | Multiple points in one call |
| `POST /coverage/area` | Polygon input, GeoJSON heatmap output |
| `GET /gateways` | Filterable gateway directory |
| `POST /optimize/placement` | Recommend new gateway locations |
| `POST /survey/upload` | Client uploads RSSI ground-truth logs |

**Format coverage as adoption-blocker.** Format support is the most common reason a platform is dropped at evaluation. All five formats are required, none optional: GeoJSON (web), GeoTIFF (ArcGIS / academic), CSV (universal), KML (Google Earth / hardware vendors), Shapefile (legacy GIS, mandatory for Vietnamese public sector).

**Stickiness mechanisms.** Webhooks (notify when coverage changes — once configured, migration is painful); official SDKs in Python, JavaScript, Go (cuts onboarding from ~2 weeks to ~1 day); public Postman collection (5-minute API evaluation); complete OpenAPI specification (signals professional engineering, enables auto-generated clients).

---

## 5. System Architecture

### 5.1 Layered architecture

```
┌────────────────────────────────────────────────────────────┐
│  CLIENT LAYER                                              │
│  Web app (MapLibre GL JS) │ Mobile app (Vietnamese, simple)│
└────────────────────────────────────────────────────────────┘
                           ↑↓
┌────────────────────────────────────────────────────────────┐
│  APPLICATION LAYER                                         │
│  Domain types, business logic, API handlers                │
│  Speaks: Coordinates, Prediction, Project, Tier            │
└────────────────────────────────────────────────────────────┘
                           ↑↓
┌────────────────────────────────────────────────────────────┐
│  REPOSITORY LAYER  (4 capabilities)                        │
│  CoverageQuery │ SurveyIngest │ GatewayDirectory │         │
│  AddressResolution                                         │
│  Speaks: data-access methods                               │
│  Hides: SQL, cascade, version coupling, stage fallback     │
└────────────────────────────────────────────────────────────┘
                           ↑↓
┌────────────────────────────────────────────────────────────┐
│  STORAGE LAYER  (2 systems mandatory at v1)                │
│                                                            │
│  PostgreSQL 17 + PostGIS 3.5 + TimescaleDB 2.17            │
│       (single instance — primary engine for queryable data)│
│                                                            │
│  S3-compatible — Cloudflare R2 (PMTiles, model artifacts)  │
│                                                            │
│  ─────────── triggered, not deployed at v1: ───────────    │
│  Valkey 8  (deployed when geocoding cache miss > 30%       │
│             sustained for 7 days)                          │
└────────────────────────────────────────────────────────────┘
```

Two storage systems by default. Valkey is a *triggered addition*, not a starting choice. The system is engineered so that adding Valkey changes only the geocoding cascade implementation — the Repository interface does not change.

### 5.2 The four capabilities

The application has exactly **four** capabilities from the data layer. No more.

| # | Capability | Purpose | Primary callers |
|---|---|---|---|
| C1 | **CoverageQuery** | Coverage prediction; tile fetch | F1 map, F2 lookup, F3 API |
| C2 | **SurveyIngest** | Receive RSSI/SNR logs | F3 `/survey/upload` |
| C3 | **GatewayDirectory** | Query and manage gateway metadata | F1 map, ML serving |
| C4 | **AddressResolution** | Address ↔ coordinates | F2 lookup |

Tile fetching lives **inside** `CoverageQuery`, not as a separate `TileService`. A tile is a pre-computed spatial query result; wrapping it as a separate service would create a shallow pass-through interface (Ousterhout Ch. 7 anti-pattern). Routing between cached tiles and on-demand inference is the actual interesting decision and belongs to one capability.

The "geocoding cache" and "model artifact storage" are **not** separate capabilities — they are implementation details of C4 and C1 respectively. Information hiding (Ch. 5).

### 5.3 Six core design principles

These principles govern every decision in the system:

1. **Modules should be deep (Ch. 4).** The data layer exposes a narrow interface (4 capabilities, ~14 methods total), but inside it carries the full complexity of SQL, geospatial queries, time-series, cache cascade, and stage fallback. Cost (interface) small; benefit (functionality) large.
2. **Information hiding (Ch. 5).** Database type, index type, schema layout, choice of cache backend, ML stage routing — all implementation details. Application code never sees the strings "Postgres", "Redis", "GiST", "Stage 4" in business logic.
3. **Pull complexity downwards (Ch. 8).** Geocoding cascade, ML stage fallback, retry logic, version mismatch handling, tile-vs-inference routing — all live inside the data layer. The application does not manage them.
4. **Different layer, different abstraction (Ch. 7).** Application speaks the business domain ("predict at this point"). Repository speaks data access ("query coverage"). Storage speaks SQL.
5. **Define errors out of existence (Ch. 10).** `Result[T, E]` for business errors. `Confidence` instead of a degraded-mode flag. Empty list instead of "not found". Quarantine as a separate table instead of a state column.
6. **Code should be obvious (Ch. 18).** Every method, schema, and constraint has a clear name and a clear reason. A new engineer should understand *why* in hours, not weeks.

### 5.4 Cost discipline as a third lens

In addition to Ousterhout's principles, every architectural decision must answer three questions in order:

1. Does it satisfy the principle? (Ousterhout)
2. What does it cost per month at v1 scale? (cost lens)
3. Can we defer it until measured demand justifies it? (cost lens)

**Hard cost rules.** No infrastructure costing > USD 50/month on day 1 without a named sponsor or measured demand. General donations never pay for Google APIs. Single region until measured load demands more. Free tier of every paid service before paid tier. Defer the second instance of anything until the first is proven to be the bottleneck.

---

## 6. Data Architecture

### 6.1 Storage stack

**PostgreSQL 17 + PostGIS 3.5 + TimescaleDB 2.17.** The single engine for all data needing structured query.

- One query language for ~90% of the logic. One hiring skill set.
- Full ACID where it is required (project workspaces, gateway directory).
- PostGIS is the OGC Simple Features reference implementation — directly compatible with QGIS / ArcGIS used by P3 government users.
- TimescaleDB hypertables for `survey_*` time-series: automatic partitioning, ~10–20× compression, still SQL.
- Free cross-domain joins: "RSSI logs from past 7 days within polygon X" is one query.

Required extensions: `postgis`, `postgis_raster`, `timescaledb`, `pg_trgm` (Vietnamese fuzzy text), `unaccent` (diacritic stripping), `pg_stat_statements`.

**Cloudflare R2 (S3-compatible).** Immutable blobs served via CDN: PMTiles, model artifacts. Chosen for zero egress fees — tiles are heavily read; egress is the dominant cost on every other provider.

**Valkey 8 — deployed only when triggered.** Not part of the v1 stack. Triggering criterion: geocoding cache cold-miss ratio sustained above 30% for 7 days, or P95 lookup latency drifting above 2 s due to address resolution. Until then, the geocoding cache lives in the `address.canonical` Postgres table — 30–50 ms slower per cold lookup but well within the 3 s end-to-end SLA. Valkey (not Redis) is chosen because Redis Labs changed the Redis license to RSAL v2 + SSPL in March 2024; Valkey is a pure-BSD fork hosted by the Linux Foundation, with an identical RESP protocol.

### 6.2 Schema design

Each capability has its own Postgres schema. Schema = namespace. Easier to migrate, back up, audit.

| Schema | Purpose | Notable structures |
|---|---|---|
| `geo` | Gateway directory | `gateways` table; GiST index on location; partial index on active gateways |
| `ts` | Survey time-series | `survey_quarantine` and `survey_training` (hypertables); BRIN on timestamp; GiST on location |
| `address` | Geocoding canonical | `canonical` table; GIN + pg_trgm on `normalized_text` (generated column via `unaccent`) |
| `audit` | Compliance log | `compliance_log`; plain table (not hypertable at v1 scale); 90-day retention |

**Quarantine and training are two separate tables**, not two states on one table. Querying the training set never requires `WHERE quarantined = false`. This is "Define special cases out of existence" (Ch. 10) applied to data structure.

The `normalized_text` column is a **generated column** (`GENERATED ALWAYS AS ... STORED`). The DBMS guarantees it stays in sync with `raw_text`. Application code cannot accidentally write inconsistent data — information hiding at the DDL level.

### 6.3 Key data structures and indexes

| Column / use case | Index / structure | Reason |
|---|---|---|
| `gateways(location)` | GiST (R-tree) | Standard spatial; OGC-compliant |
| `gateways(operator)` partial | B-tree | Fast filtering of active gateways |
| `survey_*(timestamp)` | BRIN | Append-only; billion-row scale; <0.1% of B-tree size |
| `survey_*(location)` | GiST | Spatial filter within time windows |
| `canonical(normalized_text)` | GIN + `pg_trgm` | Vietnamese fuzzy match, with or without diacritics |
| `canonical(location)` | GiST | Reverse geocoding |
| Tile lookup | S3 key prefix | Object storage; CDN edge cache |

### 6.4 Tile and model artifact layout

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

`model_version` lives in the S3 key prefix. Recalibration v17 → v18 makes old tiles "disappear" from lookup automatically — no CDN purge, no stale flag, no cleanup job. "Define errors out of existence" (Ch. 10) applied to cache invalidation.

### 6.5 Geocoding cascade (cost-disciplined)

The cascade lives inside the data layer (`repository/address_resolution/cascade.py`). The application sees only a `GeocodingDepth` enum (`CACHE_ONLY`, `CACHE_AND_LOCAL`, `INCLUDE_PROVIDERS`, `INCLUDE_PAID`) — a *resource budget*, not a business tier.

```
resolve(address, depth=CACHE_AND_LOCAL):

  step 1: Postgres canonical (always)
            P95 < 50 ms; ~95% hit on warm system

  step 2: depth ≥ CACHE_AND_LOCAL:
            self-hosted Nominatim if deployed, else skip
            P95 < 300 ms

  step 3: depth ≥ INCLUDE_PROVIDERS:
            VietMap or Goong (domestic, low cost)
            P95 < 800 ms

  step 4: depth == INCLUDE_PAID:
            Google Maps Geocoding
            ONLY if a sponsor account is configured
            P95 < 1500 ms
```

Every successful resolution at step 2+ writes back to step 1. This is how the system learns Vietnamese addresses over time.

The cost rule is enforced **in code, not in policy**: when `INCLUDE_PAID` is requested but no Google sponsor account is configured, the cascade returns `AddressUnresolved` with `reason=PAID_PROVIDER_UNAVAILABLE` rather than failing open or charging the general donation pool.

---

## 7. Machine Learning Model Architecture

### 7.1 The four-stage progression

The model is **not a fixed artifact** — it is a four-stage progression governed by operating rules. Stage selection is determined by **data volume × geographic diversity × operational maturity**, not by perceived sophistication.

| Stage | Adopt when | Approach |
|---|---|---|
| **Stage 1** — Empirical (log-distance / Friis hybrid) | < 500 ground-truth points | `PL(d) = Friis(d) + 10·(n−2)·log10(d/d₀)` for `d > d₀ = 100 m`; `PL(d) = Friis(d)` otherwise. Friis = `32.45 + 20·log10(d_km) + 20·log10(f_MHz)`. RSSI = `Pₜ + Gₜ + Gᵣ − PL`. Default tuning: AS923-2 / 923 MHz, suburban (n=3.0, σ=6 dB). No ML training. Sub-millisecond inference. Fully explainable. |
| **Stage 2** — Hybrid + LightGBM residual | ≥ 500 points across ≥ 2 terrain classes | Stage 1 predicts physical baseline; LightGBM learns the residual from a 15–25 column engineered feature vector. |
| **Stage 3** — Hybrid + CNN residual | ≥ 30,000 points **AND** Stage 3 RMSE improves ≥ 10% over Stage 2 on a spatial test set | ResNet-18 modified for regression on a 6-channel raster slice (DEM, building height, land cover, NDVI, distance encoding, Fresnel zone mask). |
| **Stage 4** — Bayesian Hybrid | ≥ 30,000 points **AND** NLL improves **AND** ECE < 0.05 | Stage 3 plus calibrated probabilistic uncertainty (deep ensembles or MC-dropout). |

### 7.2 Shared mathematical core

All four stages share the hybrid decomposition:

```
PL = PL_baseline + residual
```

This decomposition is what makes the roadmap operationally tractable: the API contract, map renderer, and gateway-placement optimizer are built once against a shared `PathLossModel.predict()` interface and continue functioning as the residual learner evolves underneath them.

```
PathLossModel.predict(tx, rx, environment) -> Prediction

Prediction:
    mean_path_loss: float                 # dB
    variance: Optional[float]             # dB², None for deterministic stages
    components: dict
        physics_baseline: float           # output of Stage 1
        residual_mean: float              # output of residual learner
        residual_variance: Optional[float] # populated by Stage 4 only
```

Downstream code never branches on stage. It consumes whatever fields are available and treats `None` as "uncertainty not yet quantified."

### 7.3 Stages are never retired

Stage 1 — the calibrated empirical model — is **never retired**. It serves three permanent roles:

1. The physics baseline in the hybrid decomposition used by Stages 2, 3, and 4.
2. The benchmark against which all subsequent stages are evaluated.
3. The fallback prediction when residual learners are unavailable, untrained for a region, or have failed calibration monitoring.

Each stage adoption is a **permanent operational commitment** — not a replacement of previous infrastructure. This cumulative burden is a primary input into transition decisions. *A team that cannot reliably maintain Stage 3 should not adopt Stage 4 regardless of dataset size.*

| Currently deployed | Models maintained | Infrastructure required |
|---|---|---|
| Stage 1 | Stage 1 only | Python, NumPy/SciPy |
| Stage 2 | Stage 1 + Stage 2 | + LightGBM training and serving |
| Stage 3 | Stage 1 + Stage 2 + Stage 3 | + GPU serving, PyTorch |
| Stage 4 | Stage 1 + Stage 2 + Stage 3 + Stage 4 | + ensemble orchestration, calibration monitoring |

### 7.4 The cascade invalidation rule

The four stages share a coupling that must be enforced explicitly: residual targets used to train Stages 2, 3, and 4 are derived from the Stage 1 baseline. Therefore:

- Each model artifact records the Stage 1 calibration version it was trained against.
- The Stage 1 calibration version lives in the S3 key prefix (`calib=v17/...`).
- Production inference asserts version consistency before combining baseline and residual.
- When Stage 1 recalibrates v17 → v18, the internal `model_router` filter no longer matches old artifacts — they "disappear" from production. No deletion, no stale flag.

A "stale model" is not a state. It is "no matching file." Define error out of existence (Ch. 10).

### 7.5 Three blocking conditions for stage transitions

A transition is **blocked** even when accuracy criteria are met if any apply:

1. **Geographic concentration.** New measurements come from regions already represented. The dataset has grown in *size* but not *diversity*. The simpler model wins.
2. **Calibration regression.** A Stage 4 candidate that improves NLL but worsens ECE. Miscalibrated uncertainty is operationally worse than no uncertainty, because users learn to trust it and act on it.
3. **Operational readiness gap.** Stage 3 needs GPU; Stage 4 needs ensemble orchestration and calibration monitoring. A team that cannot reliably maintain Stage 3 should not adopt Stage 4 regardless of dataset size — the most violated rule in ML platform projects.

> **A 2–5% accuracy improvement does NOT justify a stage transition.**

### 7.6 Migration procedure (three phases, all required)

| Phase | Duration | What happens |
|---|---|---|
| **Dual-running** | ≥ 2 weeks | Both old and new models run on production traffic. New model logged but not served. |
| **Shadow validation** | ≥ 1 week | New-model predictions compared against incoming ground-truth as it arrives. Stage 4 calibration validated on production data, not just the test set. |
| **Cutover** | — | New model becomes primary. Old stays warm 30 days behind a fallback flag. Cached predictions invalidated on a defined schedule, not all at once. |

### 7.7 Failure mode response matrix

| Failure | Detection | Automatic response |
|---|---|---|
| Version mismatch (baseline vs residual) | Artifact metadata check | Block inference, fall back to Stage 1, schedule retraining |
| Spatial generalization failure | Per-region production RMSE exceeds Stage 1 baseline RMSE | Disable residual learner for that region, fall back to Stage 1, prioritize ground-truth collection |
| Calibration drift (Stage 4) | Rolling 7-day ECE > 0.08, **or** ground-truth-in-95%-CI fraction < 0.90 | Auto-rollback to Stage 3, alert on-call |
| Inference infrastructure failure | P99 latency > 2× normal baseline | Graceful degradation to Stage 1 with `degraded_mode` flag in API response |

---

## 8. API and Output Format Design

### 8.1 Endpoints

| Endpoint | Purpose | Tier |
|---|---|---|
| `GET /coverage/point` | Single-point coverage check | Community + |
| `POST /coverage/batch` | Multi-point coverage | Professional + |
| `POST /coverage/area` | Polygon → GeoJSON heatmap | Professional + |
| `GET /gateways` | Filterable gateway directory | Community + |
| `POST /optimize/placement` | Recommend gateway locations | Enterprise |
| `POST /survey/upload` | Upload RSSI ground-truth | Academic + |

### 8.2 Output formats — all five are non-negotiable

| Format | Required by | Reason |
|---|---|---|
| GeoJSON | All web developers; default | Native to web tooling; lightweight |
| GeoTIFF | P3 government, P4 researchers | ArcGIS workflows; raster scientific use |
| CSV | All; P1 especially | Universal; spreadsheet analysis |
| KML | P6 hardware vendors, casual users | Google Earth visualization |
| Shapefile | P3 Vietnamese public sector | Legacy GIS workflows still dominant |

A platform shipping only GeoJSON will be ruled out by ~40% of professional users at the integration-evaluation stage.

### 8.3 Stickiness and developer-experience mechanisms

Webhooks notify subscribers when coverage in a defined area changes — once configured, migration is painful. Official SDKs in Python, JavaScript, and Go cut onboarding from approximately two weeks to one day. A public Postman collection enables five-minute API evaluation. A complete OpenAPI specification signals professional-grade engineering and enables auto-generated clients in any language.

---

## 9. Non-Functional Requirements

### 9.1 Performance SLAs (hard)

- Lookup end-to-end: P95 < 3 s.
- API point query: P95 < 500 ms.
- Map tile delivery from cache: P95 < 1 s.
- `simulate_with_gateway` (on-demand inference): P95 < 5 s.

### 9.2 Vietnam-first localization

The platform is *Vietnam-first by design*, not by accident.

| Domain | Localization rule |
|---|---|
| Language | Vietnamese with full diacritic support and a diacritic-stripped fallback (both "Đà Nẵng" and "Da Nang" must resolve). End-user UI never uses telecom jargon. |
| Currency | VND primary for donation interfaces and internal financial reporting; USD accepted for international grants. |
| Geocoding | Self-hosted Nominatim primary; VietMap / Goong fallback; Google last resort with dedicated sponsor only. |
| DEM data | SRTM 30 m baseline; MONRE 5 m DEM for selected urban regions. |
| Building footprints | OSM Vietnam community + Microsoft Building Footprints. |
| GIS format priority | Shapefile must be supported — Vietnamese public-sector workflows still require it. |
| Government engagement | Via tender or commissioned project; long cycles; deliver reports more than predictions. |
| Social distribution | Open Graph cards optimized for Facebook + Zalo (not Twitter or LinkedIn). |

### 9.3 Security and access control

Two Postgres roles only: `readonly_role` and `app_role`. Admin operations (creating users, dropping tables, role grants) go through migrations or DBA SSH. No separate admin role to maintain.

API secrets load from a single environment file at process start. The Repository receives a config object — it does not know the source. When a sponsor secret manager is required (e.g., Cloudflare-funded Workers), the loader implementation changes; the Repository signature does not.

Audit-required events (Shapefile/GeoTIFF export, survey upload, admin operations on user/api_key) hit `audit.compliance_log` directly via a small writer in `infrastructure/audit_writer.py`. No buffering, no async — keep it boring. Retention: 90 days.

### 9.4 Cost discipline (operating expense lens)

**Day-1 expected monthly run-rate** at v1 scale (≤ 5,000 MAU, ≤ 50,000 lookups/day, 1–2 provinces pre-computed):

| Component | Day-1 cost | Notes |
|---|---|---|
| Postgres (single VPS, 4 vCPU, 16 GB RAM, 200 GB SSD) | ~USD 30–50/mo | Hetzner / Contabo or similar EU/SG VPS |
| Cloudflare R2 storage (10 GB) | USD 0 | Free tier |
| Cloudflare R2 egress | USD 0 | Free on R2 |
| Grafana Cloud (free tier) | USD 0 | 10 k series, 14-day retention |
| Cron / scheduler | USD 0 | systemd timers on the Postgres VPS |
| Self-hosted Nominatim | USD 0 | Not deployed at v1 |
| Valkey | USD 0 | Not deployed at v1 |
| Domain + Let's Encrypt TLS | ~USD 1/mo | Domain only |
| **Subtotal** | **~USD 30–50/mo** | |

**Discipline rule.** Total monthly run-rate must stay under ~30% of the trailing-3-month donation inflow average. If it exceeds that ratio, the response is *cut a component*, not raise donations.

---

## 10. Operational Design

### 10.1 Monitoring (essential metrics only)

Every capability emits metrics to Prometheus. The Repository publishes; the application does not.

Tracked at v1: per-method request duration histogram, per-method-and-status counter, `coverage_query_stage_fallback_total`, Postgres disk usage and connection pool utilization, R2 monthly bandwidth, Stage 4 ECE rolling 7-day (auto-rollback trigger). Alert thresholds: C4 `resolve` P95 > 2 s for 5 min → page; C1 `predict` P95 > 500 ms for 5 min → warning; capability error rate > 1% for 5 min → page; Stage 4 ECE rolling 7-day > 0.08 → auto-rollback to Stage 3 + alert; Postgres disk > 70% → warning, > 85% → page.

Hosting: Grafana Cloud free tier covers v1 needs. No self-hosted Prometheus stack at v1.

### 10.2 Backup and recovery

**Postgres.** Continuous WAL archiving to R2 (enables PITR). Weekly logical `pg_dump` for `geo` and `address` schemas (small, fast recovery). `ts.*` is a hypertable — daily logical dumps would be slow and expensive; WAL covers the gap. Restore drill quarterly; measure RTO/RPO.

**Object storage (R2).** Bucket versioning on for `models-prod` only — model artifact recovery is more valuable than tile recovery (tiles are recomputable from inputs). No cross-region replication at v1; trigger condition is the first compliance demand or first paid SLA.

### 10.3 Schema migration

Tool: Alembic. Each migration carries both `upgrade()` and `downgrade()`.

Safe (migration only): add new column with default; add new index; add new table within an existing schema; rename column with a wrapping view.

Requires Repository coordination: restructure tables; change index type; rename schema.

Requires ADR + Repository major version bump: change a field in a public dataclass; change an enum value of a public type; change the semantic of a method.

**Zero-downtime rule.** Never drop a column in production until new code has run stably for ≥ 7 days.

### 10.4 Data ingestion quality pipeline

Survey uploads via `POST /survey/upload` are *not* used directly. Each record passes through:

1. Schema validation.
2. Outlier detection (RSSI outside [-150, -30] dBm rejected; SNR outside [-30, 30] dB rejected).
3. Geographic plausibility check (cannot be inside a known water surface unless the device declares maritime).
4. Reputational weighting (uploads from verified gateways and high-reputation accounts weighted higher).
5. Quarantine until the next training cycle merges verified data.

Without this pipeline, the bidirectional API becomes an attack surface against the model.

---

## 11. Risk Management

### 11.1 Strategic risks

| Risk | Mitigation |
|---|---|
| ML accuracy plateaus before users find it valuable | The hybrid decomposition (`PL_baseline + residual`) ensures the empirical baseline remains useful even if the residual learner underperforms. Never deploy only the ML layer. |
| Donation/grant funding dries up | Diversify sources (individuals, corporate sponsorship, research grants, government commissioning); maintain ≥ 6 months operating reserves; publish transparent finances. |
| Free-rider problem | Enterprise tier intake includes a soft commitment to structured survey uploads; "top contributors" leaderboard leverages reputational incentives. |
| Telecom operators (P2) build internally instead of using + contributing | Position the data flywheel — a single operator does not have multi-source crowdsourced data — as the differentiator; open-source the code to defuse "not invented here". |
| One large commercial competitor enters Vietnam | Open-source code + public data flywheel make pure feature competition difficult; reach critical data mass before they arrive. |

### 11.2 Operational risks

| Risk | Mitigation |
|---|---|
| Calibration drift in Stage 4 silently erodes user trust | Daily evaluation job, weekly recalibration check, alert thresholds (ECE > 0.08), auto-rollback. |
| Geocoding cost explosion | Aggressive permanent caching; cascading fallback ladder; never let Google touch the general donation budget. |
| Map rendering becomes a GPU cost center | Pre-computed tiles served via R2 + CDN; on-demand inference only for what-if scenarios. |
| Stage 3 / 4 adopted before the team can support it | Operational readiness gap is a blocking condition; do not transition without supporting infrastructure tested. |

### 11.3 Market risks

| Risk | Mitigation |
|---|---|
| End-user app fragmentation makes direct B2C unviable | Distribute through P1 and P7; never optimize for direct P5 acquisition. |
| B2G cycles outlast the budget | P3 is Low priority by design; treat B2G as a funding opportunity, not a proactive target. |
| Format gaps lose professional users at evaluation | All five export formats are non-negotiable from v1. |

---

## 12. Evolution Roadmap and Success Metrics

### 12.1 Hard invariants — breaking these breaks the architecture

1. Application code never imports from `infrastructure/`.
2. Application never sees the strings `postgres`, `redis`, `valkey`, `s3`, `stage_4`, `GiST`, `BRIN` in business code.
3. Every successful prediction comes with `Confidence`. A `Prediction` without confidence cannot exist.
4. Every survey upload passes through quarantine first. No "trusted uploader bypass" — reputation expresses trust as weight, never as a shortcut.
5. General donation funds never reach Google. Enforced inside the cascade, not in the application.
6. Model artifact keys contain calibration version. Recalibration never breaks downstream by deleting files.
7. The audit log records every Shapefile / GeoTIFF export.

### 12.2 Triggered evolutions (require measurement, not opinion)

| Component | Trigger | Cost impact |
|---|---|---|
| Postgres read replica | OLAP queries impacting OLTP P95 | + USD 30–50/mo |
| Valkey | Geocoding cache miss > 30% for 7 days, or P95 lookup latency drift due to address resolution | + USD 15–25/mo |
| Self-hosted Nominatim | VietMap / Goong cost > USD 30/mo or hit ratio < 70% | + USD 30–50/mo |
| Cross-region R2 replication | First compliance / paid-SLA demand | Doubles R2 storage cost |
| ClickHouse for survey logs | `ts.survey_training` > 10 B rows AND analytical queries > 30% of workload AND Postgres P95 for analytical queries > 30 s | + USD 50+/mo plus ops complexity |
| Microservice split for the Repository | Capability count > 10 AND Repository team > 5 engineers AND coordination overhead > network overhead | Implementation effort |

### 12.3 Success metrics

**Funnel.** Monthly unique lookups; lookup → account-creation rate; account → deeper-tier activation within 90 days; embedded-widget impressions per partner; deep-link share count.

**Product quality.** Coverage map RMSE per region (held-out spatial test set); per-stage RMSE comparison; ECE for Stage 4 deployments; lookup P95 end-to-end latency; API P95 per endpoint.

**Data flywheel.** Survey uploads per month (volume); survey upload geographic diversity (Gini coefficient over regions); months since last recalibration; number of regions where Stage 2 + is operational.

**Adoption and financial sustainability.** Active deployments per tier; integration-depth distribution (% using webhooks / SDK / survey upload regularly); 30/90/365-day retention by tier; donations received per quarter; grant and sponsorship funding committed; operating-reserve runway in months; community contribution volume.

---

## 13. Appendix — Quick Reference

### 13.1 Three hardest operating rules to maintain

1. *A 2–5% accuracy improvement does not justify a stage transition.* Engineering teams will always want to deploy the better model. Operating discipline rejects this.
2. *General donation funds are never spent on Google geocoding.* Only tiers with a dedicated sponsor covering Google credits may use it.
3. *Operational readiness gates technical adoption.* Stage 4 is blocked by infrastructure maturity, not by accuracy.

### 13.2 Three coupled bets — if any one fails, the other two lose most of their value

1. **Technical bet** — ML can predict coverage accurately enough for real planning decisions.
2. **Distribution bet** — Free, fast, shareable lookup produces sustained adoption at zero marginal cost.
3. **Ecosystem bet** — API integration + survey upload makes the platform the de-facto Vietnamese LoRa standard.

### 13.3 Stage transition decision table

| From → To | Adopt if | Blocked if |
|---|---|---|
| Stage 1 → 2 | ≥ 500 points across ≥ 2 terrain classes | Geographic concentration |
| Stage 2 → 3 | Stage 3 RMSE improves ≥ 10% on spatial test set | Geographic concentration; no GPU infrastructure |
| Stage 3 → 4 | NLL improves AND ECE < 0.05 | ECE worsens; no ensemble orchestration + calibration monitoring |

### 13.4 Persona priority cheat sheet

| Persona | Priority | Primary contribution | Strategic role |
|---|---|---|---|
| P1 IoT Solution Cos | High | High-quality survey uploads, real use cases | Primary B2B adoption, specifies platform into projects |
| P2 Telecom Operators | High | Large-scale infrastructure data | Largest data deals, potential sponsorship |
| P5 End Users | High | Lookup volume | Funnel mass, viral sharing |
| P4 Researchers | Medium | Open-source code, benchmarks, survey data | Data flywheel + 3–5 year talent pipeline |
| P6 Hardware Vendors | Medium | Embedded widget traffic, potential sponsorship | Distribution at zero CAC |
| P7 System Integrators | Medium | Survey uploads from field surveys | Channel multiplier into end-customer projects |
| P3 Government | Low | Sporadic grants / commissioned projects | Funding opportunity, not a strategic spine |

### 13.5 Source documents

This system design synthesizes four input specifications:

1. `customer-analysis.md` — Persona definitions and per-persona feature requirements.
2. `business-logic.md` — Operating model, flywheel, tier logic, financial sustainability.
3. `core-feature.md` — Detailed specification of the three core features and the four-stage ML roadmap.
4. `data-architecture.md` — Repository capabilities, schema, indexes, cost discipline, and operations.

Design philosophy reference: *A Philosophy of Software Design* by John Ousterhout (2018).

---

*End of system design document.*