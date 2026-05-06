# Business Logic

## LoRa Network Coverage Mapping Platform

---

## Philosophy

This document is the sibling of `core-feature.md`. Where that document describes the *technical structure* (modules, interfaces, algorithms), this one describes the **business rules** buried inside that structure — *what counts as correct, what counts as a normal input, what triggers updates, what must be kept distinct from what*.

Both rest on the principles of *A Philosophy of Software Design*:

- **Define errors out of existence** (Ch. 10): most "edge cases" of the business — duplicate measurements, re-measuring a spot with a different value, regions that haven't been measured — are not errors that need handling. They are **normal inputs with predefined behavior**.
- **Information hiding** (Ch. 5): business policies (merge strategy, tolerance radius, freshness) are **module parameters**, not `if/else` logic scattered across the codebase.
- **Pull complexity downwards** (Ch. 8): the user, and features built on top, never need to know about these rules — they are applied automatically at the layer below.
- **Single source of truth**: each business rule lives in **exactly one place** (one module, one parameter). It is never copied.

The consequence: when a rule changes (say, switching from "use the latest measurement" to "use the robust median"), the change happens at one point and does not ripple.

---

# Feature 1 — Coverage Map

> This is the first feature. Subsequent features (2, 3, ...) will introduce their own business rules, but each must obey the *rules for keeping the architecture intact under extension* listed at the end of this document, so that single-source-of-truth is preserved.

---

## 1.1. Business Contract with the User

The user walks around with the device collecting measurements, the data is pushed to the system, and the map must answer **a single question**: *"At any point in the area of interest, is this gateway's coverage strong, weak, or unknown?"*

The contract, stated tersely:

> **Give the user the best possible heatmap from all measurements collected so far, and clearly distinguish unmeasured areas from areas with weak signal.**

Every business decision underneath (which measurements to trust, how to merge them, when to refresh, how far influence extends) **does not appear in this contract**. This is a *deep contract*: thin surface, rules absorbed beneath it.

---

## 1.2. Rule for Co-located Measurements

This situation comes up constantly during real fieldwork: the same spot gets measured several times, and later readings are stronger or weaker than earlier ones. Per *define errors out of existence*, this is **not an error** — it is a normal input.

**Rule:** when several measurements fall within the same location (a configurable tolerance radius, default 10 m), the system applies **a merge policy** that returns a single value at that point. The policy is a **parameter**, not scattered logic:

| Policy | Behavior | When to use |
|---|---|---|
| `latest` (default) | Take the most recent measurement | Signal strength changes over time (new buildings, vegetation, weather) — recent readings reflect the current state |
| `weighted_mean` | Time-decayed weighted average | When you want to balance current state with long-term stability |
| `median` | Statistical median | When robustness against noise matters (multipath fading, RF collisions, outliers) |

**Business consequence:** whether the user measures the same spot once or a hundred times, whether the new reading is stronger or weaker than before, the map shows **a single, deterministic value** at that point under the chosen policy. There is no "old data overwriting new" or vice versa — only one clear rule. The user forgetting they already measured a place is no longer an "operational error"; it is an ordinary use case with a defined outcome.

---

## 1.3. Rule for Map Updates

**Contract:** when the measurement set changes (insert, update, delete), the map updates itself without manual action.

**Business rules behind the contract:**

1. **Updates are incremental, not full recomputes.** Only the area within the influence radius of the changed measurement is recomputed. The user sees the updated map immediately; compute cost does not balloon with the historical dataset size.
2. **The user does not need to know when the system refreshes.** Cache invalidation, tile refresh schedules — these are hidden details (*pull complexity downwards*). The user-facing contract stops at *"data changes → map changes"*.
3. **There is no "data not yet synchronized" state.** If a measurement has been accepted by the system, it is reflected. There is no intermediate "uploaded but not yet visible" state the user must understand.

---

## 1.4. Rule for Distinguishing "No Signal" from "No Data"

This is the most critical business rule of the feature, because **conflating these two states is the most common failure mode of coverage maps** — and once the user misreads them, every downstream decision (network expansion, gateway placement, service verification) is wrong as a result.

**Rule:**

- **Area with data, weak signal** → render in the main color gradient (e.g., light red, orange).
- **Area with no measurement inside any influence radius** → render **distinctly separate** from the gradient (gray, hatched, or transparent). Never on the signal-strength scale.

**This rule is enforced at the renderer layer; it does not rely on user interpretation.** Short of a radical UI change, there is no way for the user to confuse the two states.

---

## 1.5. Rule for Influence Radius

Each measurement has **an influence radius** (default: a fixed configurable radius; later versions may replace this with a dynamic radius depending on terrain, local measurement density, etc.).

**Business rules:**

- Inside the influence radius, coverage values are interpolated from nearby measurements.
- Outside the influence radius of *any* measurement → treated as **no data** (see 1.4); never extrapolated.
- Interpolated values are never presented as "actual measurements". In the API and exports, the two are tagged differently.

**Business reasoning:** extrapolating far beyond measured points is the fastest way for the platform to fabricate data and lose the trust of professional users. The "no extrapolation beyond influence radius" rule is *business discipline, not a technical limitation* — the technique is available, but the business does not allow it.

---

# Rules for Keeping Business Logic Intact Under Extension

Because features 2, 3, ... will keep arriving, each adding its own business rules, the three rules below ensure business logic **does not get fragmented and copied across the codebase**:

1. **Each business rule lives in exactly one place.** The merge policy (`latest` / `weighted_mean` / `median`) lives inside `MeasurementStore`; no feature reimplements it. The "no signal vs no data" rule lives inside `MapRenderer`; no feature handles it independently in its own UI layer. When the rule needs to change, only one place changes.

2. **Policies are parameters, not `if` branches.** When a new feature needs a different rule (say feature 2 wants `weighted_mean` as its default merge policy instead of `latest`), the answer is to **pass a different parameter**, not to add `if (feature == 2) ...`. If existing policies are insufficient, add a new policy to the list of choices — but it still lives in the same module.

3. **A business rule that doesn't fit an existing module is a rule of a new module, not an `if` branch in the old one.** Example: a future feature like "flag suspicious or spoofed measurements" needs a rule about source trust — that is a rule of a *new* module (e.g. `TrustPolicy`) sitting between `MeasurementStore` and `CoverageSurface`, not a few `if`s wedged into `MeasurementStore`.

---

## Summary Table

| Business question | Rule | Where it lives |
|---|---|---|
| Multiple measurements at the same location — which value is shown? | Merge policy (default: `latest`) | `MeasurementStore` |
| When does the map refresh? | Automatically when the measurement set changes; incrementally per influence radius | `CoverageSurface` → `MapRenderer` |
| What does an unmeasured area look like? | Visually distinct from weak-signal areas | `MapRenderer` |
| Do we extrapolate beyond measured points? | No. Beyond influence radius → "no data" | `CoverageSurface` |
| How does a rule change propagate? | Change the parameter at the one module that owns it; never edit multiple sites | (per the table above) |