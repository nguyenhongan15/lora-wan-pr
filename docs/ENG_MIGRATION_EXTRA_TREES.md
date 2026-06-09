# Migration Guide: Legacy XGBoost → New Extra Trees

> **Summary:** The new Extra Trees model achieves **RMSE 3.50 dBm** (test set, R²=0.8955) compared to ~10 dBm for the legacy 8-feature XGBoost model. It uses 21 features (including terrain, Fresnel, and land cover) for **direct RSSI prediction**, without relying on Stage 1 ITU.

---

## 1. What Changes?

| Aspect | Legacy Model (XGBoost 8 feat.) | New Model (Extra Trees 21 feat.) |
|--------|--------------------------------|----------------------------------|
| **Algorithm** | XGBoost Regressor | ExtraTreesRegressor (1500 trees) |
| **Features** | 8 (lat, lon, sf, gw_lat, gw_lon, distance_km, log_distance_km, delta_alt_m) | **21** (terrain, Fresnel, land cover, 3D geometry...) |
| **Target** | Stage 2 residuals (measured RSSI - ITU prediction) | **Direct RSSI** — no ITU model required |
| **Test RMSE** | ~10 dBm | **3.50 dBm** |
| **Test R²** | ~0.75 | **0.8955** |
| **API** | `predict_residual(lat, lon, sf, gw, …)` → residual | `pred(lat, lon)` → RSSI |
| **Dependencies** | `xgboost` | `scikit-learn`, `pandas`, `joblib` |

---

## 2. Package Installation

### Option A — Editable Installation (Recommended)

```bash
# From the project root
pip install -e services/ml-service
```

### Option B — Adjust PYTHONPATH

```bash
export PYTHONPATH="$PYTHONPATH:$(pwd)/services/ml-service/src"
# Or on Windows:
set PYTHONPATH=%PYTHONPATH%;%CD%\services\ml-service\src
```

### Dependencies for Inference Only

```bash
pip install scikit-learn pandas joblib
```

### Additional Dependencies for Training / Evaluation

```bash
pip install matplotlib     # for plots
pip install xgboost        # to compare against XGBoost
```

---

## 3. Usage — `pred(lat, lon)` Function

This is the main function, as simple as:

```python
from lora_ml_predict.predictor import pred

# --- Basic usage: only 2 coordinates ---
rssi = pred(16.06, 108.22)               # → -110.91 dBm
rssi = pred(20.9, 106.6)                 # → -113.84 dBm

# --- With explicit spreading factor (optional, default=12) ---
rssi = pred(16.06, 108.22, spreading_factor=9)  # → -114.09 dBm

# --- For a specific gateway ---
from lora_ml_predict.predictor import pred_with_gateway
rssi = pred_with_gateway(16.06, 108.22, "ac1f09fffe06fcf2")

# --- List available gateways ---
from lora_ml_predict.predictor import list_gateways
for gw in list_gateways():
    print(f"{gw['id']} : ({gw['lat']:.4f}, {gw['lon']:.4f})")
```

### Parameters

| Parameter | Type | Default | Description |
|------------|------|----------|-------------|
| `lat` | `float` | **required** | WGS84 latitude (degrees) |
| `lon` | `float` | **required** | WGS84 longitude (degrees) |
| `spreading_factor` | `int` | `12` | LoRa SF (7-12) |

### Error Handling

```python
# Outside Vietnam bounds (lat: 8.4-23.4, lon: 102.1-109.5)
pred(10.0, 110.0)   # → ValueError: longitude out of range

# Invalid type
pred("abc", 108.0)  # → TypeError: lat must be a number

# Invalid spreading factor
pred(16.06, 108.22, spreading_factor=99)  # → ValueError: SF must be 7-12

# Missing model (not trained yet)
pred(16.06, 108.22)  # → FileNotFoundError with instructions
```

---

## 4. Practical Example: Before vs After

### ❌ BEFORE (Legacy code with 8-feature XGBoost)

```python
from api.domain.coverage import Gateway, GatewayId, Target
from app.ml_model import Stage1ItuModel, CrcCovlibBackend

# Required:
# - Stage 1 ITU (C++ crc-covlib)
# - 8 manually computed features
# - Complete gateway object with altitude, antenna height, gain, TX power

def my_old_function(lat, lon, sf, freq, gw):
    # 1. Stage 1 prediction (ITU)
    stage1 = Stage1ItuModel(
        backend=CrcCovlibBackend(dem_directory="..."),
        env_profile=...
    )
    target = Target(latitude=lat, longitude=lon,
                    spreading_factor=sf, frequency_mhz=freq)
    pred_stage1 = stage1.predict(target, gw)

    # 2. Compute the 8 features
    distance_km = haversine(lat, lon, gw.latitude, gw.longitude)
    features = [[lat, lon, sf, gw.latitude, gw.longitude,
                 distance_km, math.log1p(distance_km),
                 gw.altitude_m + gw.antenna_height_m]]

    # 3. Residual prediction (XGBoost)
    residual = xgb_model.predict(features)[0]

    # 4. RSSI = Stage 1 prediction + residual
    rssi = pred_stage1.uplink_rssi_dbm + residual
    return rssi
```

### ✅ AFTER (New code with Extra Trees)

```python
from lora_ml_predict.predictor import pred

# No longer required:
# - ITU model (C++) ❌
# - DEM ❌
# - Manually computed 8 features ❌
# - Complete Gateway object ❌

def my_new_function(lat, lon, sf=12):
    rssi = pred(lat, lon, spreading_factor=sf)
    return rssi
```

---

## 5. How It Works Internally

`pred()` automatically:

1. ✅ **Finds the nearest gateway** among 13 DNIIT gateways
2. ✅ **Computes geometric features**: distance, delta_lat/lon, angle
3. ✅ **Uses dataset averages** for terrain/Fresnel features (no DEM required)
4. ✅ **Runs the sklearn pipeline**: imputation → StandardScaler → OneHotEncoder → ExtraTreesRegressor
5. ✅ **Returns the predicted RSSI** in dBm

> **Note:** Terrain features (`slope`, `roughness`, `fresnel_obstruction_ratio`, etc.) use **statistical fallbacks** (dataset averages), not real-time DEM data. Predictions are therefore more reliable within the training regions (Da Nang / Hai Phong).

---

## 6. Available Scripts

### `scripts/train_extra_trees.py` — Model Training

```bash
python scripts/train_extra_trees.py
```

Loads the CSV, trains an ExtraTreesRegressor, and saves it to `services/ml-service/data/`.

### `scripts/eval_extra_trees.py` — Full Evaluation with 6 Plots

```bash
python scripts/eval_extra_trees.py
```

Generates a complete report in `reports/extra-trees-comparison/`: stratified split, Extra Trees vs XGBoost comparison, and 6 PNG plots.

### `scripts/test_predictor.py` — Unit Test for `pred()`

```bash
python scripts/test_predictor.py
```

---

## 7. Important Files

| File | Purpose |
|---------|------|
| `services/ml-service/src/lora_ml_predict/predictor.py` | **Inference module** — `pred(lat, lon)` → RSSI |
| `services/ml-service/src/lora_ml_predict/app.py` | Existing FastAPI service (still using the legacy model) |
| `services/ml-service/data/extra_trees_model.joblib` | Trained sklearn pipeline (~90 MB) |
| `services/ml-service/data/terrain_fallback.json` | Fallback values for terrain features |
| `reports/extra-trees-comparison/summary.txt` | Evaluation metrics summary |
| `reports/extra-trees-comparison/06_comparison_et_vs_xgb.png` | Extra Trees vs XGBoost comparison plot |

---

## 8. Detailed Comparison

### Extra Trees vs XGBoost (same 21 features, same RSSI target)

```text
                              Extra Trees    XGBoost
Test RMSE (dBm)               3.50           3.80
Test MAE (dBm)                2.03           2.18
Test R²                       0.8955         0.8765
```

Extra Trees performs **0.30 dB better** than XGBoost on the same data. The gap compared to the legacy model (~10 dBm) is much larger because the old model used only 8 features and predicted residuals.

### By Distance Bin

*(See the plot `06_comparison_et_vs_xgb.png` in `reports/extra-trees-comparison/` for detailed results by distance bin.)*

---

## 9. Updating the FastAPI Service (`app.py`)

If you are using the existing `/predict-rssi` endpoint, here is how to update it:

```python
# In services/ml-service/src/lora_ml_predict/app.py

# ❌ BEFORE (legacy XGBoost loading)
import joblib
model = joblib.load(settings.model_path)

@app.post("/predict-rssi")
async def predict_rssi(target: TargetPayload):
    features = compute_8_features(target.lat, target.lon, ...)
    return {"rssi_dbm": model.predict(features)[0]}

# ✅ AFTER (new Extra Trees model)
from lora_ml_predict.predictor import pred

@app.post("/predict-rssi")
async def predict_rssi(payload: PredictionRequest):
    rssi = pred(
        payload.target.latitude,
        payload.target.longitude,
        spreading_factor=payload.target.spreading_factor
    )
    return {"rssi_dbm": rssi, "model": "extra_trees_v1"}
```

> **Note:** The new `predictor.py` module uses a fixed path (`services/ml-service/data/extra_trees_model.joblib`). No `LORA_ML_MODEL_PATH` environment variable is required.

---

## 10. Known Limitations

1. **Terrain features use fallback values** — Features such as `slope`, `roughness`, and `fresnel_obstruction_ratio` rely on dataset averages. No real-time DEM is used.
2. **Geographic coverage** — Trained on Da Nang + Hai Phong data. Less reliable elsewhere.
3. **Model size** — ~90 MB (1500 trees). Consider this for deployment.
4. **Automatic gateway selection** — `pred()` finds the nearest gateway. For a specific gateway, use `pred_with_gateway()`.
5. **No SF/frequency normalization** — The spreading factor (SF 7-12) is used directly as a numerical feature without normalization (which is normal for tree-based models). Frequency is automatically determined by the selected gateway.

---

## 11. Migration Checklist

- [ ] Install dependencies: `pip install scikit-learn pandas joblib`
- [ ] Install the package: `pip install -e services/ml-service`
- [ ] Run training: `python scripts/train_extra_trees.py`
- [ ] Test: `python scripts/test_predictor.py`
- [ ] Smoke test:

```bash
python -c "from lora_ml_predict.predictor import pred; print(f'Da Nang: {pred(16.06, 108.22):.2f} dBm')"
```

- [ ] Replace the old code:

```python
# OLD (25+ lines, Stage 1 ITU + XGBoost residual)
residual = predict_residual(lat, lon, sf, freq, gw_obj)
rssi = stage1_pred + residual

# NEW (1 line, direct Extra Trees RSSI)
rssi = pred(lat, lon, spreading_factor=sf)
```

- [ ] Update the FastAPI endpoint if needed (see section 9)
- [ ] Verify metrics: `cat reports/extra-trees-comparison/summary.txt`

---

> **Contact:** See `reports/extra-trees-comparison/` for the full report, or `scripts/eval_extra_trees.py` to reproduce the evaluation.