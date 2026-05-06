# Core Feature Specification

## LoRa Network Coverage Mapping Platform

---

## Design Philosophy

This document is structured around the principles of *A Philosophy of Software Design*:

- **Modules should be deep** (Ch. 4): each feature is presented as a module with a narrow interface that absorbs internal complexity.
- **Information hiding** (Ch. 5): decisions likely to change (interpolation algorithm, measurement merge policy, tile refresh schedule) are buried inside the implementation and do not appear in the interface.
- **Pull complexity downwards** (Ch. 8): higher-level features do not manage duplicate data, freshness, or cache invalidation — the lower module does.
- **Define errors out of existence** (Ch. 10): co-located measurements, sparse data, and unmeasured regions are all ordinary inputs with well-defined behavior, not errors.
- **General-purpose modules are deeper** (Ch. 6): the two features below share a single foundational module (`CoverageSurface`) instead of each one rolling its own logic.

The consequence: when a new idea arrives, the cost of extending the system scales with the size of the idea, not with the size of the codebase.

---

# Feature 1 — Coverage Map

> This is the first feature of the **LoRa Network Coverage Mapping Platform** project. Subsequent features (2, 3, ...) will be added later and will reuse the foundational modules built by this one.

---

## 1.1. Purpose

From signal-strength measurements (RSSI) collected by walking around the city with a device, display **a continuous heatmap(use machine learning)** on the map for each gateway: which areas receive a strong signal, which are weak, and which have no data yet. The visual style references `lora-coverage\core-logic\main-logic\pics\anh1.png`.

## 1.2. Interface (user-facing)

```
GET /map?gateway_id=...
→ Coverage raster layer + contour lines, rendered on a base map.
```

The contract with the user is stated briefly: *"give me the best heatmap you can from all the measurements available."* The decisions behind it — which measurements to trust, how to merge co-located readings, which interpolation algorithm to use, how often to refresh — **do not appear in the interface**. This is a *deep module* (Ch. 4): a thin interface, with complexity absorbed inside.

## 1.3. Module Decomposition

Three stacked modules, each hiding a different kind of complexity (*information hiding*, Ch. 5):

| Module | Input | Output | What is hidden |
|---|---|---|---|
| `MeasurementStore` | Raw measurements `(lat, lng, RSSI, time, gateway_id, device_id)` | Normalized measurement set | Position duplication, merge policy, spatial indexing |
| `CoverageSurface` | Normalized measurement set | Dense grid of RSSI values over the region of interest | Interpolation algorithm, extrapolation boundary, grid density, grid cache |
| `MapRenderer` | Value grid | Map tiles + contour lines | Color palette, contour thresholds, tile cache, zoom levels |

Each module can be replaced entirely without affecting the other two, as long as the contract is preserved. Most importantly: the interpolation algorithm can advance from simple IDW → Kriging → an ML model without the store or the renderer **needing to know**.

## 1.4. When measurements overlap — the more you measure, the more data you get

This situation occurs constantly during real-world surveying: you forget you already measured a spot and measure it a second or third time; the new reading is stronger or weaker than before. Following *define errors out of existence* (Ch. 10), this is not an error to handle specially — it is **ordinary input**, with well-defined behavior.

When several measurements fall within the same location (configurable tolerance radius, default 10 m), `MeasurementStore` applies a **merge policy** that returns a single value at that point. The policy is a **module parameter**, not if/else logic scattered across the code:

- `latest` (default): take the most recent measurement — sensible because signal strength shifts with the environment (trees grow, new construction appears, weather changes).
- `weighted_mean`: weighted average by temporal freshness.
- `median`: robust to outlier readings (multipath fading, radio collisions).

The consequence for the user: whether the same spot is measured once or a hundred times, whether this reading is stronger or weaker than the previous one — the map still shows a single, well-defined value at that point according to the chosen policy. There is no "old data overwriting new" or vice versa; only one clear rule.

## 1.5. Automatic updates as data grows

`CoverageSurface` subscribes to `MeasurementStore`. When the measurement set changes (add / update / delete), the grid is recomputed **incrementally** — only the grid cells within the radius of influence of the changed measurement need to be recomputed, not the entire grid. `MapRenderer` in turn subscribes to `CoverageSurface` and refreshes only the affected tiles.

The user sees the map update as data flows in without needing to know any of this (*pull complexity downwards*, Ch. 8): the complexity of cache invalidation and refresh is pushed down into the lower layer, while the upper layer sees only "data changed → map changed".

## 1.6. Regions with no data

Areas without any measurement within the radius of influence are rendered **distinctly** from areas with weak signal — typically shaded gray or hatched, outside the main gradient. Confusing "no signal" with "no data" is the most common failure mode of coverage maps, and it is ruled out at the renderer layer rather than left to user interpretation.

---

# Rules for preserving the architecture as the system grows

Since features 2, 3, ... will follow and many ideas will surface during development, the three rules below ensure that the **cost of extension scales with the size of the idea, not with the size of the codebase**:

1. **Every feature that reads coverage data goes through `CoverageSurface`.** No feature is allowed to query `MeasurementStore` directly or reimplement interpolation. Single source of truth.

2. **Algorithm changes live inside the module, not at the interface.** Upgrading IDW → Kriging → ML is a change *inside* `CoverageSurface`. The renderer, the features above, and the API documentation do not change a single line.

3. **A feature that does not fit an existing module becomes a new module, not an `if` branch in an old one.** Example: the future feature "predict coverage for a hypothetical, not-yet-installed gateway" will be a module *parallel* to `CoverageSurface`, taking different input, returning the same kind of value grid, and **reusing `MapRenderer` as is**.

---

## Summary Table

| Feature | Purpose | Deep modules it relies on |
|---|---|---|
| Coverage Map | Visualize measured signal strength | `MeasurementStore` → `CoverageSurface` → `MapRenderer` |