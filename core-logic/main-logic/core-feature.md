# Core Feature Specification

## LoRa Network Coverage Mapping Platform with ML-Based Analysis

---

**Document purpose:** This document provides a detailed specification of the three core features that form the foundation of the platform. For each feature, it defines the strategic purpose, input data requirements, expected outputs, user-facing outcomes, recommended models or technical approaches, and key risks. The three features are interdependent and together constitute a self-reinforcing data and product flywheel.

---

## Feature 1 — Coverage Map with ML Prediction

### 1.1 Strategic Purpose

A coverage map by itself has limited value; standard GIS tools can already render heatmaps from measured data. The strategic value of this feature lies in its ability to **predict coverage in areas where no field measurements exist**. This is the reason the system must be built on machine learning rather than on visualization alone.

For network operators, a single square kilometer of drive-test measurement costs millions of Vietnamese dong. A model with 85 percent predictive accuracy can therefore save billions of dong across a national network expansion plan. For IoT companies, the same capability transforms early-stage feasibility studies from a multi-week field exercise into a multi-minute desktop analysis.

### 1.2 Input Data

The model relies on the following input layers:

- **Gateway metadata.** Latitude, longitude, antenna height, transmit power, antenna gain, and radiation pattern.
- **Digital Elevation Model (DEM).** SRTM 30 m as a baseline; DEM 5 m is preferable for urban areas and can be obtained for selected regions in Vietnam from MONRE.
- **Land use and land cover.** OpenStreetMap data for building density and Sentinel-2 imagery for vegetation indices (NDVI). Vegetation has significant attenuation effects at the 868 MHz band used by LoRa in Asia.
- **Ground truth measurements.** RSSI and SNR logs from real devices. This is the most valuable training asset, and its volume directly determines model quality.
- **End-device parameters.** Spreading Factor (SF) from 7 to 12 produces dramatically different coverage radii; SF12 typically reaches four to five times further than SF7. SF must therefore be a user-configurable input.

### 1.3 Expected Output

- **Raster coverage layer** at a resolution of 100 m × 100 m (configurable) over the area of interest.
- **Per-pixel attributes:** predicted RSSI (dBm), predicted SNR (dB), serving gateway, and link budget margin.
- **Uncertainty layer.** Confidence interval or model variance for each pixel, rendered visually distinct from the prediction itself.
- **Categorical overlay** for non-technical users: Good / Marginal / No Coverage.

### 1.4 Expected User Outcomes

- **For IoT companies:** the ability to determine, before deploying any hardware, whether a planned sensor field will be reachable.
- **For network operators:** identification of underserved areas and quantitative justification for new gateway investments.
- **For system integrators:** a defensible design artifact to present to clients during pre-sales.
- **For end users:** a simple visual answer to the question, *"Will my device work here?"*

### 1.5 Recommended Modeling Approach

Model selection is driven by the volume and geographic diversity of available ground-truth measurements, not by perceived sophistication. A complex model trained on insufficient or geographically narrow data will consistently underperform a simpler model with well-engineered features.

This section is structured to separate concerns that recur across all stages from concerns specific to each stage. Subsection 1.5.1 defines the **common foundations** — shared interfaces, data pipelines, evaluation utilities, and data-versioning rules that every stage depends on. Subsections 1.5.2 through 1.5.5 specify the four stages in turn, each focusing only on what is unique to that stage. Subsection 1.5.6 addresses **stage transitions** as a first-class design concern, including dual-running, cutover criteria, and the cumulative operational complexity incurred at each stage. Subsection 1.5.7 specifies **failure modes and monitoring** with concrete thresholds and response procedures.

---

#### 1.5.1 Common Foundations

The four stages share a common architecture. Treating that architecture as an explicit, named module — rather than allowing it to emerge implicitly — prevents information leakage between layers and ensures that downstream consumers of the model are insulated from the choice of residual learner.

##### Shared Prediction Interface

Every stage exposes the same interface to downstream consumers (the API layer, the map renderer, the gateway placement optimizer). The interface is defined as:

```
PathLossModel.predict(tx, rx, environment) -> Prediction

Prediction:
    mean_path_loss: float                 # dB
    variance: Optional[float]             # dB², None for deterministic stages
    components: dict
        physics_baseline: float           # output of Stage 1 model
        residual_mean: float              # output of residual learner
        residual_variance: Optional[float] # only populated by Stage 4
```

This interface remains stable across all four stages. Stage 1 returns a `Prediction` with `variance = None` and an empty residual component. Stage 4 returns the same structure with all fields populated. Downstream code never branches on stage; it consumes whatever fields are available and treats `None` as "uncertainty not yet quantified."

This single decision is what makes the roadmap operationally tractable: the API contract, map renderer, and optimizer can be built once against this interface and continue to function as the residual learner evolves underneath them.

##### Shared Data Pipeline

Two pipelines are required across the roadmap, and both are treated as first-class modules:

- **Tabular feature pipeline.** Used by Stage 2. Computes the engineered feature vector $\mathbf{x}$ from a Tx–Rx pair and the surrounding environment. Specification given in 1.5.3.
- **Raster pipeline.** Used by Stages 3 and 4. Computes the multi-channel raster slice $\mathbf{R}$ from a Tx–Rx pair. Specification given in 1.5.4 and reused unchanged in 1.5.5.

Critically, the **terrain class encoding, building footprint sources, and NDVI compositing must be defined once** and consumed identically by both pipelines. Inconsistency here is a common silent failure mode in projects with multiple modeling stages, because residual targets computed under one terrain definition cannot be compared against predictions computed under another.

##### Spatial Cross-Validation Utility

Every model in the roadmap — including the empirical baseline — is evaluated using **spatial cross-validation**, in which train and validation regions are separated by geographic boundaries rather than by random splits. Random splits produce optimistic and misleading accuracy figures because adjacent measurements are strongly correlated.

A single utility provides this functionality and is invoked identically across all stages. The utility accepts a measurement set and returns a sequence of (train, test) region pairs. Stages do not implement their own splitting logic.

##### Shared Evaluation Harness

A single evaluation harness computes the metrics required for stage selection and stage transition:

- RMSE and MAE on a held-out spatial test set (all stages)
- Negative Log-Likelihood and Expected Calibration Error (Stage 4 only)
- Per-region breakdown to detect geographic generalization failures

Cross-stage comparisons — required for the decision criteria in 1.5.6 — depend on the harness producing identical metric computations regardless of which stage is being evaluated.

##### Data Versioning and Cascade Rules

The hybrid architecture introduces a coupling that must be managed explicitly: **the residual targets used to train Stages 2, 3, and 4 are derived from the Stage 1 model output**. Therefore:

- Recalibration of the Stage 1 model invalidates the training targets of all subsequent stages.
- Each model artifact records the version of the Stage 1 calibration it was trained against.
- Production inference asserts version consistency before combining baseline and residual; mismatches trigger an alert and a fallback to Stage 1 alone.

This rule is what allows continuous improvement of the empirical baseline (as new ground truth accumulates) without silently breaking downstream models.

---

#### 1.5.2 Stage 1 — Fewer than 500 ground-truth points: Empirical model

At this data volume, machine learning is not viable: the dataset is too small to support reliable training and validation. The recommended approach is to deploy a **log-distance path loss model** with locally calibrated coefficients. The model requires no training in the machine-learning sense, executes with sub-millisecond inference latency, and is fully explainable.

##### Mathematical Formulation

$$
PL(d) = PL_0 + 10 \cdot n \cdot \log_{10}\left(\frac{d}{d_0}\right) + X_\sigma + \sum_{i} C_i
$$

Where $PL_0$ is the reference path loss at distance $d_0$, $n$ is the path loss exponent fitted per terrain class, $X_\sigma$ is the shadow fading margin, and $C_i$ are optional environmental correction terms (per-building attenuation, vegetation loss, seasonal rainfall adjustment).

Predicted received signal strength is given by the link budget:

$$
RSSI = P_{tx} + G_{tx} + G_{rx} - PL(d)
$$

##### Calibration Procedure

Group measurements by terrain class using the shared terrain definition from 1.5.1. For each class, fit $PL_0$ and $n$ via ordinary least squares on the relationship between measured path loss and $\log_{10}(d/d_0)$. Compute $X_\sigma$ as the residual standard deviation. Even with as few as 50 to 100 measurements per terrain class, the fit is sufficiently stable to outperform any uncalibrated textbook model.

##### Role Beyond Stage 1

The calibrated Stage 1 model is **never retired**. It serves three permanent roles:

1. The physics baseline in the hybrid decomposition used by Stages 2, 3, and 4.
2. The benchmark against which all subsequent stages are evaluated.
3. The fallback prediction when residual learners are unavailable, untrained for a region, or have failed calibration monitoring.

---

#### 1.5.3 Stage 2 — 500 to 50,000 ground-truth points: Hybrid Log-Distance + LightGBM Residual

The Stage 1 model continues to predict the physical baseline, while a **LightGBM** model learns the residual — the systematic error that the physics-based component cannot explain.

##### Mathematical Formulation

$$
\widehat{PL}(d, \mathbf{x}) = PL_{\text{log-dist}}(d) + f_{\text{LGBM}}(\mathbf{x})
$$

The LightGBM training target is the measured residual:

$$
y_{\text{train}} = PL_{\text{measured}} - PL_{\text{log-dist}}(d)
$$

This formulation forces the model to focus exclusively on unexplained variance rather than re-learning the distance–path-loss relationship.

##### Tabular Feature Pipeline

The pipeline produces a feature vector of approximately 15 to 25 columns. Recommended features:

- Elevation difference between Tx and Rx
- Maximum elevation along the line-of-sight path
- Count of buildings intersecting the line-of-sight path
- Mean NDVI along the propagation path
- Percentage of the path crossing built-up land cover
- Percentage of the path crossing water surfaces
- Terrain class at the receiver and at the transmitter
- Average rainfall at the receiver location (seasonal)
- Spreading Factor
- Antenna height of the serving gateway

Distance and reference path loss are deliberately excluded — their contribution is already accounted for by the Stage 1 component.

##### Rationale for LightGBM

LightGBM is selected for native handling of categorical features (avoiding one-hot expansion), training speed three to five times faster than alternative implementations (material for a platform that ingests crowdsourced measurements continuously), and lower memory footprint during serving.

##### Inference

Inference latency remains in the sub-millisecond to single-millisecond range on commodity CPU hardware via the shared interface in 1.5.1.

##### Limitations

Model quality is bounded by the quality of feature engineering, which requires a working understanding of radio propagation physics. As the dataset grows toward and beyond 30,000 measurements, the marginal value of additional engineered features diminishes.

---

#### 1.5.4 Stage 3 — 30,000 or more ground-truth points: Hybrid Log-Distance + CNN Residual

The residual component upgrades from a tabular model to a **Convolutional Neural Network**, taking advantage of its ability to extract spatial patterns directly from raster representations of the propagation environment — patterns that hand-engineered features cannot fully encode (knife-edge diffraction over chains of terrain peaks, reflection from large water surfaces, building-cluster scattering, Fresnel-zone obstruction).

##### Mathematical Formulation

$$
\widehat{PL}(d, \mathbf{R}) = PL_{\text{log-dist}}(d) + f_{\text{CNN}}(\mathbf{R}; \boldsymbol{\theta})
$$

##### Raster Pipeline (shared with Stage 4)

This pipeline is treated as a first-class module independent of the model. It produces a fixed-size tensor of shape $C \times H \times W$ where $H = W = 256$ pixels. Each slice is geometrically aligned along the Tx–Rx axis with the transmitter at a canonical position (e.g., left edge, center row), removing rotational variance.

| Channel | Source | Purpose |
|---|---|---|
| Digital Elevation Model | SRTM 30 m or local DEM 5 m | Terrain obstruction and diffraction |
| Building height | OSM + Microsoft Building Footprints | Urban shadowing |
| Land cover (one-hot, 4–6 classes) | OpenStreetMap, ESA WorldCover | Material and clutter modeling |
| NDVI | Sentinel-2 (seasonal composite) | Vegetation attenuation |
| Distance-from-Tx encoding | Computed | Spatial position along path |
| Fresnel zone mask | Computed | Highlights propagation-critical region |

Channels are standardized independently using statistics computed on the training set only.

##### CNN Architecture

A lightweight backbone is used; heavier architectures invite overfitting. The recommended starting point is a **ResNet-18** modified for regression:

$$
f_{\text{CNN}}(\mathbf{R}; \boldsymbol{\theta}) = h_{\text{regress}}\big(g_{\text{pool}}\big(\phi_{\text{ResNet-18}}(\mathbf{R})\big)\big)
$$

The first convolution accepts $C$ input channels rather than the default 3. Global average pooling produces a 512-dimensional feature vector. The regression head is two fully connected layers ($512 \to 128 \to 1$) with ReLU and dropout ($p = 0.3$).

##### Loss Function

**Huber loss** is used, which is more robust than MSE to heavy-tailed RSSI measurement noise:

$$
\mathcal{L}_{\delta}(y, \hat{y}) =
\begin{cases}
\frac{1}{2}(y - \hat{y})^2 & \text{if } |y - \hat{y}| \leq \delta \\
\delta \cdot \left(|y - \hat{y}| - \frac{1}{2}\delta\right) & \text{otherwise}
\end{cases}
$$

A typical value is $\delta = 5$ dB, approximately one shadow-fading standard deviation at 868 MHz.

##### Training and Inference

Training and evaluation use the spatial cross-validation utility from 1.5.1. Data augmentation is restricted to operations that preserve propagation physics: vertical flip (the Tx–Rx axis is symmetric) and small additive noise on continuous channels. Horizontal flip is **not** applied, as it reverses Tx–Rx direction. Adam optimizer, learning rate $10^{-3}$, cosine annealing, batch size 64, weight decay $10^{-4}$.

Inference latency rises to approximately 10–100 ms per query on GPU, 50–300 ms on CPU.

##### Limitations

The CNN reduces but does not eliminate dependency on data diversity. Spatial cross-validation is essential. Explainability degrades relative to Stage 2; tools such as Grad-CAM provide partial mitigation, and the decomposed output (*"physics baseline X dB, CNN correction Y dB"*) exposes high-level attribution to enterprise auditors.

---

#### 1.5.5 Stage 4 — 30,000+ ground-truth points with mature operations: Bayesian Hybrid Model

The Stage 3 model produces a single point estimate of path loss. Downstream consumers — gateway placement optimizers, SLA calculators, deployment risk assessments — have no way to distinguish reliable predictions from speculative ones. Stage 4 addresses this by replacing the deterministic CNN residual learner with a **Bayesian residual learner** that outputs a full probability distribution.

##### Two Sources of Uncertainty

- **Aleatoric uncertainty** — irreducible measurement noise (multipath fading, hardware tolerances). More data does not reduce this component.
- **Epistemic uncertainty** — model uncertainty arising from limited training data in the relevant region of input space. Shrinks as additional ground truth is collected.

For operational use, epistemic uncertainty signals *"collect more data here"*; aleatoric uncertainty signals *"this location is inherently variable, plan accordingly."* Conflating them destroys the operational value of uncertainty quantification.

##### Mathematical Formulation

The hybrid decomposition is preserved. The residual is now a random variable. Each member of a **Deep Ensemble** of $M$ networks (typically 5 to 10) outputs a Gaussian distribution:

$$
r_m(\mathbf{R}) \sim \mathcal{N}\big(\mu_m(\mathbf{R}), \; \sigma_m^2(\mathbf{R})\big)
$$

The predictive mean and variance, decomposed into aleatoric and epistemic components, are:

$$
\mu_*(\mathbf{R}) = \frac{1}{M}\sum_{m=1}^{M} \mu_m(\mathbf{R})
$$

$$
\sigma_*^2(\mathbf{R}) = \underbrace{\frac{1}{M}\sum_{m=1}^{M} \sigma_m^2(\mathbf{R})}_{\text{aleatoric}} + \underbrace{\frac{1}{M}\sum_{m=1}^{M}\big(\mu_m(\mathbf{R}) - \mu_*(\mathbf{R})\big)^2}_{\text{epistemic}}
$$

The variance decomposition is the central technical advantage: aleatoric and epistemic components can be reported separately to downstream consumers via the `variance` and `residual_variance` fields of the shared `Prediction` interface.

##### Architecture and Loss

Each ensemble member preserves the ResNet-18 backbone from Stage 3 but extends the regression head to produce two outputs — a mean and a log-variance:

$$
\big[\mu_m(\mathbf{R}), \; \log \sigma_m^2(\mathbf{R})\big] = h_{\text{regress}}^{(m)}\big(g_{\text{pool}}\big(\phi_{\text{ResNet-18}}^{(m)}(\mathbf{R})\big)\big)
$$

Training uses the **Gaussian negative log-likelihood**:

$$
\mathcal{L}_{\text{NLL}}(y, \mu, \sigma^2) = \frac{(y - \mu)^2}{2\sigma^2} + \frac{1}{2}\log\sigma^2 + \text{const}
$$

This loss is self-balancing: increasing $\sigma^2$ reduces the first term but is penalized by the second, forcing predictions whose error magnitude matches the predicted uncertainty (calibration).

##### Operational Use of Uncertainty

The strategic value of Stage 4 lies in how uncertainty estimates flow into downstream features:

- **Coverage map rendering.** Pixels with high epistemic variance are visually distinguished through reduced opacity or hatching.
- **Active learning.** The platform prioritizes regions of high epistemic uncertainty when recommending where field measurements are most valuable.
- **Risk-aware gateway placement.** The optimizer maximizes coverage area subject to a guarantee that 95% of locations meet a minimum signal threshold, rather than maximizing expected coverage alone.
- **SLA reporting.** Predictions with credible intervals can be defended in commercial agreements where deterministic estimates cannot.

##### Inference Cost

Inference latency scales linearly with ensemble size. For $M = 5$, end-to-end latency is approximately 50–500 ms per query. Stage 4 is therefore appropriate for **pre-computed tile generation and offline analytics, not for high-throughput real-time endpoints** without ensemble parallelization or model distillation.

---

#### 1.5.6 Stage Transitions and Operational Complexity

Stage transitions are designed as deliberate engineering events, not implicit upgrades. This subsection specifies when to transition, when not to transition, how to execute the transition, and the cumulative operational burden incurred.

##### Decision Rules

| Transition | Adoption rule |
|---|---|
| Stage 1 → 2 | Adopt when training set exceeds 500 measurements with at least 2 represented terrain classes |
| Stage 2 → 3 | Adopt if and only if $\dfrac{\text{RMSE}_{\text{Stage 2}} - \text{RMSE}_{\text{Stage 3}}}{\text{RMSE}_{\text{Stage 2}}} \geq 0.10$ on a spatial test set |
| Stage 3 → 4 | Adopt if and only if $\text{NLL}_{\text{Stage 4}} < \text{NLL}_{\text{Stage 3}}$ **and** $\text{ECE}_{\text{Stage 4}} < 0.05$ |

A 2–5 percent improvement in accuracy does not justify a stage transition. The increased operational complexity, infrastructure cost, and inference latency outweigh marginal accuracy gains.

##### When NOT to Transition

Three conditions block a transition even when accuracy criteria are met:

1. **Geographic concentration.** If new measurements come from the same regions as existing data, the dataset has grown in size but not in diversity. The simpler model is retained.
2. **Calibration regression.** A Stage 4 candidate that improves NLL but degrades ECE indicates miscalibrated uncertainty and is not deployed.
3. **Operational readiness gap.** Stage 3 requires GPU infrastructure; Stage 4 requires ensemble orchestration and calibration monitoring. A transition is blocked until the supporting infrastructure is in place and tested.

##### Migration Procedure

Each transition follows a fixed three-phase procedure:

1. **Dual-running phase (minimum 2 weeks).** Both old and new models run in parallel on production traffic. The new model's predictions are logged but not served. Per-region accuracy and latency are monitored.
2. **Shadow validation (minimum 1 week).** New model predictions are compared against incoming ground-truth measurements as they arrive. Calibration metrics (for Stage 4) are validated on production data, not just the held-out test set.
3. **Cutover.** New model becomes primary. Old model remains warm for 30 days, callable via an explicit fallback flag. Cached predictions from the old model are invalidated according to a defined schedule, not all at once.

##### Cumulative Operational Burden

A frequently underestimated cost of the staged roadmap is that earlier stages are not retired when later stages are adopted. The table below specifies what must be maintained at each operational point:

| Currently deployed | Models maintained in production | Infrastructure required |
|---|---|---|
| Stage 1 | Stage 1 only | Python, NumPy/SciPy |
| Stage 2 | Stage 1 (baseline + benchmark) + Stage 2 | + LightGBM training and serving |
| Stage 3 | Stage 1 + Stage 2 (benchmark) + Stage 3 | + GPU serving, PyTorch |
| Stage 4 | Stage 1 + Stage 2 (benchmark) + Stage 3 (fallback) + Stage 4 | + ensemble orchestration, calibration monitoring |

This cumulative burden should be a primary input into the transition decision. A team that cannot reliably maintain Stage 3 infrastructure should not adopt Stage 4 regardless of dataset size.

---

#### 1.5.7 Failure Modes and Calibration Monitoring

Each stage introduces its own failure modes. Detection metrics, thresholds, and response procedures are specified explicitly rather than left to operational improvisation.

##### Failure Modes by Stage

| Stage | Failure mode | Detection | Response |
|---|---|---|---|
| All | Stage 1 recalibration cascades to invalidate downstream model targets | Version mismatch between baseline and residual artifacts | Block inference, fall back to Stage 1, schedule retraining of residual model |
| 2, 3, 4 | Spatial generalization failure (model deployed to a region underrepresented in training) | Per-region RMSE on production data exceeds Stage 1 baseline RMSE for that region | Disable residual learner for that region, fall back to Stage 1, prioritize ground-truth collection |
| 4 | Calibration drift | Rolling 7-day ECE on production exceeds 0.08, **or** rolling 7-day fraction of ground-truth values within the predicted 95% credible interval drops below 0.90 | Auto-rollback to Stage 3, alert on-call engineer, schedule retraining |
| 3, 4 | Inference infrastructure failure (GPU outage, memory pressure) | Inference latency P99 exceeds 2× normal baseline | Graceful degradation to Stage 1 prediction with explicit `degraded_mode` flag in the API response |

##### Monitoring as a First-Class Concern

Calibration is fragile. A poorly calibrated Stage 4 model is operationally worse than a well-calibrated Stage 3 point estimate, because users learn to trust the uncertainty estimates and act on them.

The following are required production capabilities, not nice-to-haves:

- A daily evaluation job comparing the past 24 hours of ground-truth uploads against the corresponding model predictions, computing per-stage RMSE, MAE, ECE, and the per-region breakdown.
- A weekly recalibration check that retrains the Stage 1 calibration coefficients on the full accumulated dataset and flags any significant drift.
- An alerting threshold defined for each metric, with explicit responsibility assigned to a named team.

Without this monitoring layer, the staged roadmap silently degrades into the worst of both worlds: complex infrastructure delivering predictions whose quality is no longer verified.

---

#### Summary

The four-stage progression preserves a single mathematical core — the hybrid decomposition $PL = PL_{\text{baseline}} + r$ — across increasing levels of residual-learner sophistication. The shared interfaces, data pipelines, and monitoring infrastructure defined in 1.5.1 ensure that downstream consumers and operational tooling do not need to be rebuilt as the residual learner evolves. Stage transitions are explicit engineering events governed by quantitative decision rules, and the cumulative operational burden of each stage is disclosed so that adoption decisions can be made with full visibility into long-term cost.

### 1.6 Performance and Rendering Considerations

A single province at 100 m × 100 m resolution may contain several million pixels. Real-time inference for every user query is not feasible. The recommended strategy is:

- **Pre-compute coverage tiles** for the current gateway configuration and serve them as vector tiles in PMTiles or MBTiles format.
- **On-demand inference for "what-if" scenarios only.** When a user drags a hypothetical gateway onto the map, inference runs over a localized area surrounding that gateway.
- **MapLibre GL JS** for the front-end rendering layer, avoiding licensing costs that would otherwise grow with scale.

### 1.7 Risks and Pitfalls

The most common failure mode is rendering a heatmap without uncertainty information. A region predicted as "well covered" with 50 percent confidence must be visually distinguishable from a region predicted as "well covered" with 95 percent confidence. Uncertainty should be communicated through transparency, hatching, or a secondary color channel. This is the dividing line between a toy and an engineering instrument.

---

## Feature 2 — Address and Coordinate Lookup

### 2.1 Strategic Purpose

This feature is not primarily a technical capability; it is the **acquisition funnel** for the entire platform. A user searching online for *"LoRa coverage check Da Nang"* lands on a page with a single address field, enters a location, and receives a result within two seconds. This moment converts an anonymous visitor into a qualified lead.

Every persona passes through this entry point, including senior engineers at telecom operators who will test the platform informally before opening a sales conversation. The feature must therefore be inexpensive to operate, fast enough to feel instantaneous, and shareable.

### 2.2 Input Data

The lookup must accept multiple input formats:

- **Vietnamese addresses with and without diacritics** (e.g., *"Đà Nẵng"* and *"Da Nang"*).
- **Non-standard or colloquial addresses** (e.g., *"the road I live on near Cho Con market"*), with a graceful fallback to manual map selection when the geocoder cannot resolve the input.
- **Decimal coordinates and DMS coordinates.**
- **Direct map tap** on the visual interface.
- **Current GPS location** on mobile devices.
- **Bulk CSV upload**, available to all users and used heavily by IoT companies and system integrators.

### 2.3 Geocoding Architecture for Vietnam

Geocoding in Vietnam presents a structural challenge that is rarely addressed openly. Google Maps Geocoding API offers the best coverage but at significant cost (approximately USD 5 per 1,000 requests). OpenStreetMap Nominatim is free but underperforms in Vietnam, particularly outside major urban centers. The recommended stack is:

- **Primary:** self-hosted Nominatim with an OpenStreetMap Vietnam extract, fine-tuned for common local place names.
- **Fallback:** VietMap API or Goong, both domestic providers offering substantially lower cost than Google.
- **Aggressive caching.** Every successfully resolved address is stored permanently to avoid repeated paid lookups.

### 2.4 Expected Output

The output is structured in two simultaneous layers, allowing a single feature to serve technical and non-technical users.

**Layer 1 — End-user view:**

- A status indicator: 🟢 Good Coverage, 🟡 Marginal, 🔴 No Coverage.
- A single-sentence explanation in plain Vietnamese.
- A small map image showing the queried location.

**Layer 2 — Technical view (revealed on demand):**

- Predicted RSSI in dBm.
- Predicted SNR in dB.
- Recommended Spreading Factor.
- Nearest serving gateway, with distance and a link to inspect that gateway on the main map.
- Confidence score for the prediction.

### 2.5 Expected User Outcomes

- **End users** receive a clear, actionable answer without exposure to telecommunications terminology.
- **Engineers** access the underlying technical detail with a single click.
- **Hardware vendors** embed the lookup widget into their commercial websites, allowing prospective buyers to verify compatibility before purchase.
- **System integrators** validate site feasibility during initial client calls.

### 2.6 Distribution and Virality Mechanisms

The lookup feature is the most natural surface for organic distribution. Three mechanisms are recommended:

- **Shareable deep links** of the form `app.com/check?lat=16.07&lng=108.22`, opening directly to the result for any recipient.
- **Auto-generated Open Graph images** containing a map snapshot and the coverage status, ensuring shared links render attractively on Facebook, Zalo, and similar platforms.
- **Embeddable widget** allowing hardware vendors to integrate the coverage check into their own e-commerce sites. A single vendor selling 10,000 IoT units per month generates 10,000 monthly lookups for the platform at zero acquisition cost.

### 2.7 Risks and Pitfalls

The dominant risk is response latency. A lookup taking longer than three seconds breaks the perception of fluency and significantly reduces conversion. End-to-end latency, including geocoding, model inference, and rendering, must be budgeted explicitly during architecture design.

---

## Feature 3 — API and Data Export

### 3.1 Strategic Purpose

The API is not merely a feature; it is the **competitive moat** of the platform. Once an IoT company or system integrator has integrated the API into their internal systems, switching costs become substantial. The API is therefore the strongest available mechanism for retaining business customers — stronger than visual polish, and stronger than competitive pricing.

A secondary strategic effect is data acquisition: a well-designed API includes an upload endpoint that allows partner systems to contribute RSSI logs back to the platform, continuously improving model accuracy.

### 3.2 Minimum Endpoint Specification

| Endpoint | Purpose | Primary Users |
|---|---|---|
| `GET /coverage/point` | Single-point coverage check | IoT companies, end users, hardware vendors |
| `POST /coverage/batch` | Multiple points in one call | IoT companies, system integrators |
| `POST /coverage/area` | Polygon input, GeoJSON heatmap output | Telecom operators, government, system integrators |
| `GET /gateways` | Filterable gateway directory | IoT companies, telecom operators, researchers |
| `POST /optimize/placement` | Recommend new gateway locations | IoT companies, telecom operators, system integrators |
| `POST /survey/upload` | Client uploads RSSI ground-truth logs | System integrators, researchers |

The final endpoint is strategically important: it converts the API from a one-way service into a bidirectional data pipeline. Each uploaded log is a new training sample. This is the mechanism by which the platform's model improves over time while competitors' do not.

### 3.3 Input Data per Endpoint

- **Point and batch queries:** coordinates, optional Spreading Factor, optional device class.
- **Area queries:** GeoJSON polygon, target resolution, output format.
- **Optimization queries:** project boundary, candidate-site constraints, budget or count limit, weighting between coverage area and cost.
- **Survey uploads:** timestamped RSSI and SNR records, device identifier, gateway identifier (when known), and location.

### 3.4 Expected Output Formats

Format support is frequently underestimated and is a common cause of lost deals. Different personas use different tools, and the absence of a single format can disqualify the platform from consideration.

- **GeoJSON.** Default for web developers and most programmatic consumers.
- **GeoTIFF.** Required by government agencies using ArcGIS and by academic researchers.
- **CSV.** Used universally, particularly by IoT companies for spreadsheet analysis.
- **KML.** Used by Google Earth users and many hardware vendors.
- **Shapefile.** Required for legacy GIS workflows, which remain common in Vietnamese public-sector contexts.

### 3.5 Expected User Outcomes

- **Developers** can integrate coverage data into their own applications within hours rather than weeks.
- **Operators** can pull bulk coverage analyses into their internal network planning tools.
- **Researchers** can export raw datasets for academic work without procedural friction.
- **System integrators** can automate site survey workflows and bill-of-materials generation.

### 3.6 Stickiness Mechanisms

Several capabilities significantly increase customer retention and are often overlooked.

- **Webhooks.** Notify subscribers when coverage in a defined area changes — for example, when a new gateway is added or an existing gateway goes offline. Once a customer has configured webhooks, migration to a competitor becomes substantially harder.
- **Official SDKs** in Python, JavaScript, and Go. SDKs typically reduce customer onboarding time from approximately two weeks to one day.
- **Public Postman collection.** Allows engineers to evaluate the API within five minutes of discovery.
- **Complete OpenAPI specification.** Enables automatic client generation in any language and signals professional-grade engineering to enterprise buyers.

### 3.7 Risks and Pitfalls

A high-quality API with poor documentation is functionally equivalent to no API. Documentation investment must match API investment in scope and ongoing maintenance. Many Vietnamese startups have built strong APIs but failed to scale because every new customer required manual sales support to navigate undocumented behavior.

---

## Interaction Between the Three Features

The three features are not independent. They constitute a **product and data flywheel**:

1. **Free lookup attracts users** — generating leads at zero marginal cost.
2. **The ML coverage map demonstrates technical credibility** — converting leads into paying customers.
3. **The API retains customers and ingests ground-truth data** through the survey upload endpoint — improving the model, which improves the map, which improves lookup accuracy, which strengthens the funnel.

Each feature reinforces the next. If the development budget must be reduced, the recommendation is to deliver an early version (v0.1) of all three rather than to deliver one or two of them at higher polish. Removing any single feature breaks the flywheel.

---

## Summary Table

| Feature | Primary Strategic Function | Critical Success Factor |
|---|---|---|
| Coverage Map with ML Prediction | Product core and technical credibility | Predictive accuracy and visible uncertainty |
| Address and Coordinate Lookup | Acquisition funnel and free entry point | Sub-three-second response and shareability |
| API and Data Export | Customer retention and data ingestion | Format coverage and documentation quality |

---