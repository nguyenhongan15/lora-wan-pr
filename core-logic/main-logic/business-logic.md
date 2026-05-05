# Business Logic — End-to-End Project

## LoRa Network Coverage Mapping Platform with ML-Based Coverage Analysis

> **Document purpose.** Consolidate the rules, decision flows, constraints, and dependencies that constitute the project's "business logic" — serving both engineering/product and business/funding audiences. This document does not restate the feature specifications or technical specs of the two source files (`core-feature.md`, `customer-analysis.md`); it extracts the rules and reasoning *behind* them in a form that can drive decisions.

---

## Table of Contents

1. Executive Summary
2. Operating Model — The Product Flywheel
3. Customer Segmentation Logic
4. Core Product Logic (Three Features)
5. ML Model & Data Logic
6. Growth & Distribution Logic
7. Use-Case Tier Logic (All Free)
8. Operational & Decision Rules
9. Vietnam Localization Logic
10. Output Format Logic
11. Risk Management
12. Success Metrics
13. Appendix — Quick Reference

---

## 1. Executive Summary

The platform delivers **one fundamental capability** — *predicting LoRa coverage where no one has measured it* — packaged across three feature surfaces that together form a self-reinforcing flywheel. It is positioned for the Vietnamese IoT market and serves seven customer segments with deliberately uneven priority.

**The platform is fully free at every access level.** Sustainability comes from donations, community contributions, grants, sponsorships, and open-source development — not from paid tiers. User groups are still differentiated, but the differentiation is by *use case* (individual / academic / professional / enterprise / OEM), not by payment.

The model rests on three coupled bets:

1. **Technical bet.** ML can predict coverage accurately enough that organizations will adopt the platform for real planning decisions instead of treating it as a curiosity. One km² of drive testing costs millions of VND; an 85%-accurate model across a national expansion plan saves billions — value that justifies the operational integration we want from enterprise users.
2. **Distribution bet.** A free, fast, shareable address-lookup feature produces sustained adoption volume across all user groups at zero marginal cost, feeding both data ingestion and community visibility.
3. **Ecosystem bet.** Once an API is integrated into a user's internal systems and survey-upload becomes part of their workflow, the platform becomes the de-facto Vietnamese LoRa standard. This position is more durable than commercial lock-in because it is reinforced by every contribution back to the model — not by a switching bill.

If any of the three bets fails, the other two lose most of their value. **This is the single most important principle in this document: the three core features are non-negotiable as a set.**

---

## 2. Operating Model — The Product Flywheel

The flywheel runs in three continuously-recurring phases:

**Phase A — Free lookup attracts users.** A user searches "LoRa coverage check Da Nang" on Google, lands on a page with a single address field, gets a result in under three seconds, and is converted from anonymous visitor to identified user. Lookup is the feature designed to maximize top-of-funnel volume — the input to every later phase.

**Phase B — The ML map demonstrates technical credibility.** Senior engineers at telecom operators and IoT solution companies will not integrate a platform whose map looks like a textbook tutorial into a real workflow. **Predictions paired with visible uncertainty** are the proof artifact that converts users from "curious" to "committed" — i.e., willing to integrate, contribute data, and recommend it to colleagues.

**Phase C — The API anchors users and ingests data.** Once a user has integrated `/coverage/batch` or `/optimize/placement` into their internal systems, the cost of *leaving the platform* is weeks of engineering — even though no bill is issued for leaving. Critically, `POST /survey/upload` lets those same users contribute RSSI logs back, which trains the model that improves the map that improves lookup accuracy that strengthens the funnel.

**The flywheel is asymmetric.** Remove Phase A → starve the funnel. Remove Phase B → users stop at "tried it once." Remove Phase C → the model stagnates, the ecosystem doesn't grow, and the de-facto-standard position erodes.

> **Budget consequence.** When development budget must be cut, **never** cut one of the three core features. The correct response is to ship v0.1 of all three rather than v1.0 of one or two.

---

## 3. Customer Segmentation Logic

Seven personas are defined. Priority is *not* a function of total addressable market — it is a function of **data flywheel contribution × adoption volume × ecosystem leverage**.

### 3.1 Priority Logic

| Priority | Personas | Reason for ranking |
|---|---|---|
| **High** | P1 IoT Solution Companies, P2 Telecom Operators, P5 End Users | P1 has an active strategic question (rent vs build) that the platform answers directly, and is the source of the highest-quality survey uploads. P2 has the largest infrastructure, generating the largest ground-truth volume once integrated. P5 is high-priority by *volume* (free lookup). |
| **Medium** | P4 Researchers/Students, P6 Hardware Vendors, P7 System Integrators | Each provides leverage rather than direct contribution: P4 feeds the data flywheel + open-source contributions + produces tomorrow's enterprise engineers; P6 distributes lookup at zero CAC; P7 puts the platform into deployment projects for end customers. |
| **Low** | P3 Smart City / Government | B2G cycles are long, procurement runs through tenders, the buyer wants *reports* more than *predictions*. Pursue opportunistically (especially when funding/grant opportunities arise from their side); not a strategic spine. |

### 3.2 Value Mapping — Which Feature Serves Which Persona

| Persona | F1 ML Map | F2 Lookup | F3 API |
|---|---|---|---|
| P1 IoT Solution Cos | **Critical** — feasibility & cost decisions | Used informally before sales call | **Critical** — embed coverage layer in their dashboards |
| P2 Telecom Operators | **Critical** — replaces drive testing | Low | High — bulk planning workflows |
| P3 Government | High — provincial overview reports | Low | Medium — GIS integration |
| P4 Researchers | Medium — model benchmarking | Low | **Critical** — raw data export |
| P5 End Users | Low — abstracted away | **Critical** — the only feature they ever see | None |
| P6 Hardware Vendors | Low | **Critical** — embeddable widget on their store | Medium — device-network compatibility |
| P7 System Integrators | High — pre-sales artifacts | Used during site visits via mobile | **Critical** — survey upload, BoM automation |

This mapping is the foundation for tier logic in Section 7: features that are *critical* to high-priority personas determine which tier gets the deepest access; features that are *critical* to medium-priority personas serve as growth and distribution levers.

### 3.3 Per-Persona Distribution Logic

**P5 is never targeted as a primary outreach channel.** The user base is geographically and economically fragmented — even with a free model, the operating cost of running direct outreach to this group exceeds the adoption value returned. P5 is reached through P1 (which specifies the platform into their IoT solutions) and P7 (which deploys it on customer projects). The platform's logic for P5 is therefore: **make the mobile app radically simple, make the deep links viral, and let P1/P7 do the distribution.**

**P6 plays an inverted role.** The embeddable widget on their e-commerce store generates inbound traffic for the platform. A vendor selling 10,000 IoT units per month delivers 10,000 monthly lookups at zero acquisition cost.

---

## 4. Core Product Logic

### 4.1 Feature 1 — ML Coverage Map

**Strategic role.** Technical credibility. This is the artifact that demonstrates the platform is more than a heatmap renderer.

**Core operating rule:** *Predicted coverage must always be paired with visible uncertainty.* A region predicted "well covered" with 50% confidence must be visually distinguishable from one predicted "well covered" with 95% confidence. Rendering predictions without uncertainty is the dividing line between a toy and an engineering instrument — and it disqualifies the platform from serious adoption by enterprise users.

**User-configurable inputs that change the output:** Spreading Factor (SF7–SF12) and hypothetical gateway-placement scenarios. SF12 reaches 4–5× further than SF7; this *must* be exposed because the same physical infrastructure produces dramatically different coverage maps under different SF assumptions, and user decisions depend on which SF is realistic for their use case.

**Performance rule.** Per-province pre-computed tiles in PMTiles/MBTiles. Real-time inference is reserved exclusively for "what-if" scenarios when a user drags a hypothetical gateway. This is the only architecture that scales to multiple provinces without a GPU bill that breaks operating economics.

### 4.2 Feature 2 — Address & Coordinate Lookup

**Strategic role.** Acquisition funnel. Every persona — including senior engineers at P2 — passes through this entry point.

**Hard latency budget:** *End-to-end response under 3 seconds, including geocoding, model inference, and rendering.* A lookup taking longer than three seconds breaks the perception of fluency and significantly reduces conversion. **This is an operating-level SLA, not a technical preference.**

**Two-layer output rule:** Every lookup returns simultaneously:
- **Layer 1 (default):** 🟢/🟡/🔴 status, one-sentence Vietnamese explanation, map snapshot.
- **Layer 2 (revealed on click):** RSSI in dBm, SNR in dB, recommended SF, nearest serving gateway with link, confidence score.

This dual-layer logic is what allows a single feature to serve P5 and a P2 senior engineer in the same session. Hiding Layer 2 disqualifies the platform from enterprise evaluation; exposing Layer 2's terminology to end users disqualifies it from them.

**Virality mechanisms (must be built — not optional):**
1. Shareable deep links: `app.com/check?lat=16.07&lng=108.22`
2. Auto-generated Open Graph cards for Facebook/Zalo previews
3. Embeddable widget for hardware vendor sites

### 4.3 Feature 3 — API & Data Export

**Strategic role.** Both retention anchor AND data ingestion pipeline.

**The bidirectional rule.** The API is not just read endpoints. `POST /survey/upload` accepts user-contributed RSSI logs, each of which becomes a training sample. This converts *every API user* into a data contributor — the mechanism by which the platform's model improves over time *while competitors' models do not.* Because access is free, the expectation of contributing data back must be made explicit in API documentation and terms of use.

**Format coverage as an adoption-blocker.** Format support is the most common reason a platform is dropped at the evaluation stage by professional users. Required formats — *all of them, none optional*: GeoJSON (web), GeoTIFF (ArcGIS / academic), CSV (universal), KML (Google Earth / hardware vendors), Shapefile (legacy GIS / Vietnamese public sector). Missing any single format can disqualify the platform from integration.

**Stickiness mechanisms:**
- Webhooks (notifying subscribers when coverage changes — once configured, migration is painful)
- Official SDKs in Python, JavaScript, Go (cuts user onboarding from ~2 weeks to ~1 day)
- Public Postman collection (5-minute API evaluation)
- Complete OpenAPI spec (signals professional-grade engineering; enables auto-generated clients)

---

## 5. ML Model & Data Logic

The model is **not a fixed artifact** — it is a four-stage progression governed by operating rules. Stage selection is determined by **data volume × geographic diversity × operational maturity**, not by perceived sophistication.

### 5.1 The Stage Progression as a Decision Tree

| Stage | Adopt when | Retire previous stage? |
|---|---|---|
| **Stage 1** — Empirical (log-distance) | <500 ground-truth points | — |
| **Stage 2** — Hybrid + LightGBM | ≥500 points across ≥2 terrain classes | **No** — Stage 1 stays as baseline & fallback |
| **Stage 3** — Hybrid + CNN | ≥30,000 points **AND** Stage 3 RMSE improves on Stage 2 by ≥10% | **No** — Stages 1 & 2 retained as benchmark |
| **Stage 4** — Bayesian Hybrid | ≥30,000 points **AND** NLL improves **AND** ECE < 0.05 | **No** — Stage 3 retained as fallback |

> **Critical operating principle: stages are never retired.** Each stage adoption increases cumulative operational burden permanently. Treat this as a *cost of growth*, not a technical detail.

### 5.2 When NOT to Transition (Three Blocking Conditions)

A stage transition is *blocked* even when accuracy criteria are met if any of the following applies:

1. **Geographic concentration.** New measurements come from regions already represented in the existing data. The dataset has grown in *size* but not in *diversity*. The simpler model wins.
2. **Calibration regression.** A Stage 4 candidate improves NLL but worsens ECE. *Miscalibrated uncertainty is operationally worse than no uncertainty*, because users learn to trust it and act on it.
3. **Operational readiness gap.** Stage 3 requires GPU; Stage 4 requires ensemble orchestration + calibration monitoring. *A team that cannot reliably maintain Stage 3 should not adopt Stage 4 regardless of dataset size.* This is the single most violated rule in ML platform projects.

> **A 2–5% accuracy improvement does NOT justify a stage transition.** Operational complexity, infrastructure cost, and inference latency outweigh marginal accuracy gains.

### 5.3 The Cascade Invalidation Rule

The four stages share a hybrid mathematical decomposition: `PL = PL_baseline + residual`. This coupling must be *enforced as an operating rule*:

- Recalibrating Stage 1 → invalidates the training targets of Stages 2/3/4.
- Each model artifact records the Stage 1 calibration version it was trained against.
- Production inference asserts version consistency *before* combining baseline and residual.
- Mismatch → fires an alert + automatic fallback to Stage 1 alone.

This rule is what allows **continuous improvement of the empirical baseline (as new ground truth accumulates) without silently breaking downstream models.** Without it, recalibration becomes a feared operational event rather than a routine one.

### 5.4 Migration Procedure (Three Phases — All Required)

| Phase | Duration | What happens |
|---|---|---|
| **Dual-running** | ≥2 weeks | Both old and new models run on production traffic. New model logged but *not served*. Per-region accuracy and latency monitored. |
| **Shadow validation** | ≥1 week | New model predictions compared against incoming ground-truth as it arrives. Stage 4 calibration validated on production data, not just the test set. |
| **Cutover** | — | New model becomes primary. Old stays warm 30 days behind a fallback flag. Cached predictions invalidated on a defined schedule, not all at once. |

This procedure exists because *a stage transition that goes wrong silently erodes user trust faster than any other failure mode.*

### 5.5 Failure Mode Response Matrix

| Failure | Detection | Automatic response |
|---|---|---|
| Version mismatch (baseline vs residual) | Artifact metadata | Block inference, fall back to Stage 1, schedule retraining |
| Spatial generalization failure | Per-region production RMSE exceeds Stage 1 baseline RMSE for that region | Disable residual learner for that region, fall back to Stage 1, prioritize ground-truth collection |
| Calibration drift (Stage 4) | 7-day rolling ECE > 0.08, **OR** fraction of ground-truth values inside the predicted 95% CI < 0.90 | Auto-rollback to Stage 3, alert on-call |
| Inference infrastructure failure | P99 latency > 2× normal baseline | Graceful degradation to Stage 1 with `degraded_mode` flag in API response |

The `degraded_mode` flag is itself an operating decision: it preserves uptime at the cost of *honestly admitting reduced accuracy*. The alternative — failing closed — is worse for user trust over the long run.

---

## 6. Growth & Distribution Logic

### 6.1 Acquisition Channels Ranked by Cost

1. **Free lookup with viral surfaces (zero CAC).** Deep links + Open Graph cards distribute organically through Facebook and Zalo.
2. **Hardware vendor widget embedding (zero CAC, partner-driven).** One vendor with 10K monthly product page views delivers 10K monthly lookups.
3. **Academic / research relationships (zero CAC, lagged).** Today's students become tomorrow's engineers at P1/P2. The Academic tier is therefore a *3–5 year talent pipeline investment*, not a charity feature.
4. **System integrator partnerships (low CAC, leveraged).** P7 specifies the platform into projects deployed for P5; the platform inherits the deal flow.
5. **Direct outreach to P1/P2 (highest CAC).** Necessary but expensive; lookup-based qualification must do most of the work before direct outreach engages.

### 6.2 Retention Mechanism Logic

Retention scales with **integration depth**, not feature count. Because the platform is free, switching cost here is not about protecting revenue — it is *evidence of how invested the user is in the ecosystem*, and that investment is what produces survey uploads, code contributions, and word-of-mouth amplification.

- **Lookup-only user** → switching cost = zero. Not a retention target at this layer.
- **Casual API user** → switching cost = a few hours of refactoring. Mild retention.
- **API user with webhooks configured** → switching cost = days. Integration has become habitual.
- **API user with SDK + webhooks + survey upload + bulk endpoints** → switching cost = weeks. Has become part of internal workflow; high probability of contributing data back, writing about the platform, recommending to peers.

The product roadmap should therefore prioritize *moving existing users up this ladder* over acquiring new users at the same depth. This is how the data flywheel is fed without revenue.

---

## 7. Use-Case Tier Logic (All Free)

The platform is *fully free*. Tiering is not a monetization mechanism — it exists to (a) plan infrastructure (heavy users need to be known in advance for capacity planning), (b) grant deeper access to users who have demonstrated commitment to the ecosystem, and (c) shape the experience to fit each use case (individual differs from enterprise differs from OEM).

### 7.1 Recommended Tier Structure

| Tier | Target | Features unlocked | Reason for separating |
|---|---|---|---|
| **Community** | P5, casual P1, evaluating P2 engineers, all new users | Single-point lookup, basic web map, basic mobile app, deep link & widget viewing | Top of funnel. Friction must be minimal — no signup, no account. |
| **Academic / Research** | P4 | + Raw data export, sandbox for user-built models, comparison against classical propagation models, generous API rate limits for research | Data flywheel + 3–5 year talent pipeline. Requires academic verification to prevent abuse. |
| **Professional / SI** | P7, small P1 | + Site survey mode in mobile, bulk CSV upload, automatic BoM generation, project workspace, white-label reports | Productivity tooling for project work. Account required to persist workspace. |
| **Enterprise / Operator** | Large P1, P2, P3 | + Full API + SDK, webhooks, optimization endpoint, multi-tenant SLA, multi-operator comparison heatmap, dedicated support channel | Deep operational integration. Account required for capacity planning + typically accompanied by a soft commitment to contribute structured survey uploads. |
| **OEM / Partner** | P6 | + White-label widget, custom branding, device-network compatibility matrix listing, deep-link tracking | Distribution partnership. Requires partner agreement (a soft framework, no fee). |

### 7.2 Feature Gating Logic Per Tier

Gating features by tier is *not* about extracting payment (there is none). The purposes are:

- **Infrastructure load management.** Bulk operations, the optimization endpoint, and webhooks all consume far more CPU/RAM than single lookups. Opening these to anonymous users invites DoS; we need to know who the workload belongs to in order to rate-limit reasonably.
- **Data quality protection.** Survey uploads from verified accounts (Academic, Enterprise) carry higher reputational weight than anonymous uploads (see Section 8.4).
- **UX appropriate to use case.** The Community UI shows only 🟢/🟡/🔴 for end users; the Enterprise UI offers dashboards, audit logs, and multi-tenant views.

Tier-unlocking rules:

- **Community** requires no account.
- **Academic** unlocked via academic email verification (`.edu.vn`, `.edu`, etc.) or letter of introduction.
- **Professional / SI** unlocked via standard account + work email verification.
- **Enterprise / Operator** unlocked via an intake process (with a soft commitment to contribute survey upload data when available).
- **OEM / Partner** unlocked via a partner agreement — still no fee.

Limits that *should not* exist at any tier: rate limits low enough to prevent casual evaluation, format restrictions on basic outputs (GeoJSON / CSV must be open at every tier), or requiring an account for single-point lookup.

### 7.3 Financial Sustainability Model

Because there is no direct revenue, the platform must run on a diversified set of funding sources to reduce single-point-of-failure risk:

| Source | Role | Operational notes |
|---|---|---|
| **Individual & corporate donations** | Most flexible source, recurring | Requires Vietnam-friendly payment infrastructure (MoMo, ZaloPay, bank transfer) + transparent expenditure reporting |
| **Research / innovation grants** | Larger funding tied to projects | NAFOSTED, MOST, innovation funds, EU H2020/Horizon, JICA, USAID — long cycles, so multiple submissions should run in parallel |
| **Hardware vendor & operator sponsorships** | Stable mid-term funding | P2/P6 partners benefit from the platform; sponsorship in exchange for logo + roadmap-priority influence (never private features) |
| **Government / smart-city contracts** | Sporadic opportunities | P3 sometimes commissions specific deployments (e.g., a coverage map for one province) — funds flow into the general operating pool |
| **Code & data contributions** | Reduces development cost | Open-source repository + clear roadmap + good first issues; every merged PR or accepted dataset reduces operating cost |

Budget-discipline rules:

- **No sponsorship that demands private features**, because that breaks the free + open-source principle.
- **Public financial transparency** (quarterly reports) — this is a survival requirement for the donation model.
- **Maintain at least 6 months of operating reserves** before expanding feature scope — donation/grant inflows are uneven.

---

## 8. Operational & Decision Rules

This section consolidates the rules that govern day-to-day platform behavior.

### 8.1 Cascading Invalidation

When Stage 1 is recalibrated:
1. All Stage 2/3/4 models trained against the previous calibration are flagged *stale*.
2. Predictions from stale models continue to serve under a `stale_artifact` flag for ≤7 days.
3. Retraining is scheduled within 7 days.
4. After 7 days, stale models are blocked at the inference layer; affected regions fall back to Stage 1.

### 8.2 Hard Service-Level Rules

- Lookup end-to-end latency: **< 3 s P95** (operating-level SLA, not a target).
- API point query latency: < 500 ms P95.
- Coverage map tile delivery: < 1 s P95 from cache.
- Model predictions *must* include uncertainty for any tier from Professional upward (these tiers use predictions to make real deployment decisions); the Community UI may hide uncertainty for simplicity, but *must not* fabricate apparent certainty.
- API responses *must* truthfully populate the `degraded_mode` flag whenever fallback is in effect.

### 8.3 Geocoding Stack Decision Rule

Geocoding is among the platform's largest proportional operating expenses. Because the budget is donation/grant-based, cost discipline here is *more important* than under a commercial model. Cascade:

1. **Cache first.** Every successfully resolved address is permanently stored — this is the single largest cost saving.
2. **Self-hosted Nominatim** with a Vietnam OSM extract.
3. **Fallback to VietMap or Goong** (domestic providers, much cheaper than Google).
4. **Fallback to Google Maps Geocoding** *only when* Enterprise/OEM tier requires high-precision resolution AND has a *dedicated sponsor* covering that Google cost (e.g., a hardware OEM funding Google credits for their widget). General donation funds are *never* burned on Google.

Community/Academic/Professional users never reach Google geocoding through the general budget. If lookup volume balloons beyond plan, accept reduced resolve quality (drop down the cascade) before exceeding the budget.

### 8.4 Data Ingestion Quality Rules

Survey uploads via `/survey/upload` are *not* used directly. They pass through:
1. Schema validation.
2. Outlier detection (RSSI outside [-150, -30] dBm rejected).
3. Geographic plausibility check (cannot be inside a known water surface unless device declares maritime).
4. Reputational weighting (uploads from verified gateways and high-reputation accounts weighted higher).
5. Quarantine until the next training cycle.

Without this pipeline, the bidirectional API becomes an attack surface against the model.

---

## 9. Vietnam Localization Logic

The platform is *Vietnam-first by design*, not by accident.

| Domain | Localization rule |
|---|---|
| Language | Vietnamese with full diacritic support and a diacritic-stripped fallback (both "Đà Nẵng" and "Da Nang" must resolve). End-user UI *never* uses telecom jargon. |
| Currency | VND is primary for donation interfaces and internal financial reporting; USD accepted for international grants. |
| Geocoding | Self-hosted Nominatim primary; VietMap/Goong fallback; Google last resort with dedicated sponsor only. |
| DEM data | SRTM 30m baseline; MONRE 5m DEM where available, especially urban Vietnam. |
| Building footprints | OSM Vietnam community + Microsoft Building Footprints. |
| GIS format priority | Shapefile *must* be supported — Vietnamese public-sector workflows still require it. |
| Government engagement | Via tender or commissioned project; long cycles; deliver *reports* more than *predictions*. P3 is therefore a *funding opportunity* (grants, commissioned deployments), not a strategic spine. |
| Social distribution | Open Graph cards optimized for Facebook + Zalo (not Twitter / LinkedIn). |

---

## 10. Output Format Logic

Format coverage is treated as an *adoption-blocker*, not a nice-to-have. Each format maps to a specific persona's existing workflow:

| Format | Required by | Reason |
|---|---|---|
| GeoJSON | All web developers; default | Native to web tooling; lightweight |
| GeoTIFF | P3 government, P4 researchers | ArcGIS workflows; raster scientific use |
| CSV | All; P1 especially | Universal; spreadsheet analysis |
| KML | P6 hardware vendors, casual users | Google Earth visualization |
| Shapefile | P3 Vietnamese public sector | Legacy GIS workflows still dominant |

A platform that ships only GeoJSON will be ruled out by ~40% of professional users at the integration-evaluation stage. This is why all five formats are non-negotiable.

---

## 11. Risk Management

### 11.1 Strategic Risks

| Risk | Mitigation |
|---|---|
| ML accuracy plateaus before users find it valuable | The hybrid decomposition (`PL_baseline + residual`) ensures the empirical baseline remains useful even if the residual learner underperforms; *never* deploy only the ML layer |
| Donation/grant funding dries up | Diversify sources (individual donations + corporate sponsorship + research grants + government commissioning); maintain ≥6 months of operating reserves; publish transparent finances to keep donor trust |
| Free-rider problem (large users consume but never contribute data back) | Enterprise tier intake includes a soft commitment to structured survey uploads; publicly display a "top contributors" leaderboard to leverage reputation incentives |
| Telecom operators (P2) build internally instead of using + contributing | Position the data flywheel — a single operator does not have multi-source crowdsourced data — as the differentiator; open-source the code to defuse "not invented here" |
| One large commercial competitor enters Vietnam | Open-source code + public data flywheel make pure feature competition difficult; reach critical data mass before they arrive |
| Public LoRa networks consolidate, reducing the rent-vs-build decision | Pivot the value proposition toward private network optimization for vertical industries (agriculture, logistics) |

### 11.2 Operational Risks

| Risk | Mitigation |
|---|---|
| Calibration drift in Stage 4 silently erodes user trust | Required production monitoring (daily evaluation job, weekly recalibration check, alert thresholds) |
| Geocoding cost explosion | Aggressive permanent caching; cascading fallback ladder; *never* let Google touch the general donation budget |
| Map rendering becomes a GPU cost center | Pre-computed tiles; on-demand inference *only* for what-if scenarios |
| Stage 3/4 adopted before the team can support it | The operational readiness gap is itself a blocking condition; do not transition without supporting infrastructure tested |

### 11.3 Market Risks

| Risk | Mitigation |
|---|---|
| End-user app fragmentation makes direct B2C unviable | Distribute through P1 (specifies platform) and P7 (deploys it); *never* optimize for direct P5 acquisition |
| B2G cycles outlast the budget | P3 is Low priority by design; do not over-invest in tender chasing; treat B2G as a *funding opportunity* when it appears, not as a proactive target |
| Format gaps lose professional users at evaluation | All five formats are non-negotiable from v1 |

---

## 12. Key Success Metrics

### 12.1 Funnel Metrics
- Monthly unique lookups (top of funnel)
- Lookup → account-creation rate
- Account → activation of a deeper tier (Professional, Enterprise) within 90 days
- Embedded widget impressions per partner
- Deep-link share count

### 12.2 Product Quality Metrics
- Coverage map RMSE per region (held-out spatial test set)
- Per-stage RMSE comparison (input to transition decisions)
- ECE for Stage 4 deployments
- Lookup P95 end-to-end latency
- API P95 latency per endpoint

### 12.3 Data Flywheel Metrics
- Survey uploads per month (volume)
- Survey upload geographic diversity (Gini coefficient over regions)
- Months since last recalibration
- Number of regions where Stage 2+ is operational vs Stage 1 only

### 12.4 Adoption & Financial Sustainability Metrics
- Active deployments per tier (Community / Academic / Professional / Enterprise / OEM), monthly
- Integration-depth distribution (% of users using webhooks / SDK / survey upload regularly)
- 30/90/365-day retention by tier
- Adoption per channel (organic search, viral deep links, partner widget, SI partnership, academic)
- Donations received per quarter (individual + corporate)
- Grant & sponsorship funding committed
- Operating-reserve runway in months
- Community contribution volume (PRs merged, survey uploads, translations, issue triage)

---

## 13. Appendix — Quick Reference

### 13.1 Non-Negotiable Principles

1. **The flywheel is indivisible.** Ship v0.1 of all three core features rather than v1.0 of one or two.
2. **Predictions without uncertainty are not products.** The line between toy and engineering instrument is uncertainty visualization.
3. **Stages are never retired.** Each stage adoption is a permanent operational commitment.

Additional principles under the donation/open-source model:

4. **No private features.** Every feature is free and open-source; sponsorship cannot buy private features — only logo placement and priority on the public roadmap.
5. **Public financial transparency** (quarterly reports) is a survival condition of the donation model.

### 13.2 Three Hardest Operating Rules to Maintain

1. *A 2–5% accuracy improvement does not justify a stage transition.* Engineering teams will always want to deploy the better model. Operating discipline rejects this.
2. *General donation funds are never spent on Google geocoding.* Only tiers with a dedicated sponsor covering Google credits may use it.
3. *Operational readiness gates technical adoption.* Stage 4 is blocked by infrastructure maturity, not by accuracy.

### 13.3 Persona Priority Cheat Sheet

| Persona | Priority | Primary contribution | Strategic role |
|---|---|---|---|
| P1 IoT Solution Cos | High | High-quality survey uploads, real use cases | Primary B2B adoption, specifies platform into projects |
| P2 Telecom Operators | High | Large-scale infrastructure data | Largest data deals, potential sponsorship |
| P5 End Users | High | Lookup volume | Funnel mass, viral sharing |
| P4 Researchers | Medium | Open-source code + benchmarks + survey data | Data flywheel + 3–5 year talent pipeline |
| P6 Hardware Vendors | Medium | Embedded widget traffic + potential sponsorship | Distribution at zero CAC |
| P7 System Integrators | Medium | Survey uploads from field surveys | Channel multiplier into end-customer projects |
| P3 Government | Low | Sporadic grants / commissioned projects | Funding opportunity, not a spine |

### 13.4 ML Stage Transition Decision Table (Summary)

| From → To | Adopt if | Blocked if |
|---|---|---|
| Stage 1 → 2 | ≥500 points across ≥2 terrain classes | Geographic concentration |
| Stage 2 → 3 | Stage 3 RMSE improves ≥10% on spatial test set | Geographic concentration; no GPU infrastructure |
| Stage 3 → 4 | NLL improves **AND** ECE < 0.05 | ECE worsens; no ensemble orchestration + calibration monitoring in place |

### 13.5 The Flywheel in One Diagram

```
Free lookup (CAC = 0)
        ↓ attracts users
ML map with uncertainty
        ↓ proves credibility, converts users into committed participants
API integration + survey upload
        ↓ deepens integration + ingests contributed data
Better model → Better map → Better lookup accuracy → Wider adoption
        ↺ loop
```

Break any single link and the loop weakens. This is the feasibility test for every future scope-cut decision.

---

*End of document.*