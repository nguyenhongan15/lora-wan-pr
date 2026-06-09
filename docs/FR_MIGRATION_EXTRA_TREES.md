# Guide de Migration : Ancien XGBoost → Nouveau Extra Trees

> **Résumé :** Le nouveau modèle Extra Trees atteint **RMSE 3.50 dBm** (test set, R²=0.8955) contre ~10 dBm pour l'ancien modèle XGBoost à 8 features. Il utilise 21 features (dont terrain, Fresnel, occupation du sol) pour une prédiction **RSSI directe**, sans passer par le Stage 1 ITU.

---

## 1. Qu'est-ce qui change ?

| Aspect | Ancien modèle (XGBoost 8 feat.) | Nouveau modèle (Extra Trees 21 feat.) |
|--------|--------------------------------|---------------------------------------|
| **Algorithme** | XGBoost Regressor | ExtraTreesRegressor (1500 arbres) |
| **Features** | 8 (lat, lon, sf, gw_lat, gw_lon, distance_km, log_distance_km, delta_alt_m) | **21** (terrain, Fresnel, occupation du sol, géométrie 3D…) |
| **Cible** | Résidus Stage 2 (RSSI mesuré - prédiction ITU) | **RSSI direct** — pas besoin du modèle ITU |
| **Test RMSE** | ~10 dBm | **3.50 dBm** |
| **Test R²** | ~0.75 | **0.8955** |
| **API** | `predict_residual(lat, lon, sf, gw, …)` → résidu | `pred(lat, lon)` → RSSI |
| **Dépendances** | `xgboost` | `scikit-learn`, `pandas`, `joblib` |

---

## 2. Installation du package

### Option A — Installation editable (recommandée)

```bash
# Depuis la racine du projet
pip install -e services/ml-service
```

### Option B — Ajuster le PYTHONPATH

```bash
export PYTHONPATH="$PYTHONPATH:$(pwd)/services/ml-service/src"
# ou sur Windows :
set PYTHONPATH=%PYTHONPATH%;%CD%\services\ml-service\src
```

### Dépendances pour l'inférence seulement

```bash
pip install scikit-learn pandas joblib
```

### Dépendances supplémentaires pour l'entraînement / évaluation

```bash
pip install matplotlib     # pour les plots
pip install xgboost        # pour comparer avec XGBoost
```

---

## 3. Utilisation — Fonction `pred(lat, lon)`

C'est la fonction principale, aussi simple que :

```python
from lora_ml_predict.predictor import pred

# --- Usage de base : 2 coordonnées seulement ---
rssi = pred(16.06, 108.22)               # → -110.91 dBm
rssi = pred(20.9, 106.6)                 # → -113.84 dBm

# --- Avec spreading factor explicite (optionnel, défaut=12) ---
rssi = pred(16.06, 108.22, spreading_factor=9)  # → -114.09 dBm

# --- Pour une gateway spécifique ---
from lora_ml_predict.predictor import pred_with_gateway
rssi = pred_with_gateway(16.06, 108.22, "ac1f09fffe06fcf2")

# --- Lister les gateways disponibles ---
from lora_ml_predict.predictor import list_gateways
for gw in list_gateways():
    print(f"{gw['id']} : ({gw['lat']:.4f}, {gw['lon']:.4f})")
```

### Paramètres

| Paramètre | Type | Défaut | Description |
|-----------|------|--------|-------------|
| `lat` | `float` | **requis** | Latitude WGS84 (degrés) |
| `lon` | `float` | **requis** | Longitude WGS84 (degrés) |
| `spreading_factor` | `int` | `12` | SF LoRa (7-12) |

### Gestion des erreurs

```python
# Hors bornes Vietnam (lat: 8.4-23.4, lon: 102.1-109.5)
pred(10.0, 110.0)   # → ValueError: longitude hors limites

# Type invalide
pred("abc", 108.0)  # → TypeError: lat doit être un nombre

# Spreading factor invalide
pred(16.06, 108.22, spreading_factor=99)  # → ValueError: SF doit être 7-12

# Modèle manquant (pas encore entraîné)
pred(16.06, 108.22)  # → FileNotFoundError avec instructions
```

---

## 4. Exemple concret : Avant vs Après

### ❌ AVANT (ancien code avec XGBoost 8 features)

```python
from api.domain.coverage import Gateway, GatewayId, Target
from app.ml_model import Stage1ItuModel, CrcCovlibBackend

# Nécessitait :
# - Stage 1 ITU (C++ crc-covlib)
# - 8 features calculées à la main
# - Gateway complète avec altitude, hauteur d'antenne, gain, TX power

def mon_ancienne_fonction(lat, lon, sf, freq, gw):
    # 1. Prédiction Stage 1 (ITU)
    stage1 = Stage1ItuModel(
        backend=CrcCovlibBackend(dem_directory="..."),
        env_profile=...
    )
    target = Target(latitude=lat, longitude=lon,
                    spreading_factor=sf, frequency_mhz=freq)
    pred_stage1 = stage1.predict(target, gw)

    # 2. Calcul des 8 features
    distance_km = haversine(lat, lon, gw.latitude, gw.longitude)
    features = [[lat, lon, sf, gw.latitude, gw.longitude,
                 distance_km, math.log1p(distance_km),
                 gw.altitude_m + gw.antenna_height_m]]

    # 3. Prédiction du résidu (XGBoost)
    residual = xgb_model.predict(features)[0]

    # 4. RSSI = prédiction Stage 1 + résidu
    rssi = pred_stage1.uplink_rssi_dbm + residual
    return rssi
```

### ✅ APRÈS (nouveau code avec Extra Trees)

```python
from lora_ml_predict.predictor import pred

# Plus besoin :
# - du modèle ITU (C++) ❌
# - du DEM ❌
# - des 8 features calculées à la main ❌
# - de l'objet Gateway complet ❌

def ma_nouvelle_fonction(lat, lon, sf=12):
    rssi = pred(lat, lon, spreading_factor=sf)
    return rssi
```

---

## 5. Comment ça marche en interne

`pred()` fait automatiquement :

1. ✅ **Trouve la gateway la plus proche** parmi 13 gateways DNIIT
2. ✅ **Calcule les features géométriques** : distance, delta_lat/lon, angle
3. ✅ **Utilise les moyennes du dataset** pour les features terrain/Fresnel (pas de DEM nécessaire)
4. ✅ **Exécute le pipeline sklearn** : imputation → StandardScaler → OneHotEncoder → ExtraTreesRegressor
5. ✅ **Retourne le RSSI prédit** en dBm

> **Note :** Les features terrain (`slope`, `roughness`, `fresnel_obstruction_ratio`, etc.) utilisent des **fallbacks statistiques** (moyennes du dataset), pas de données DEM temps réel. Les prédictions sont donc plus fiables dans les régions de l'entraînement (Da Nang / Hai Phong).

---

## 6. Scripts disponibles

### `scripts/train_extra_trees.py` — Entraînement du modèle

```bash
python scripts/train_extra_trees.py
```

Charge le CSV, entraîne ExtraTreesRegressor, sauvegarde dans `services/ml-service/data/`.

### `scripts/eval_extra_trees.py` — Évaluation complète avec 6 plots

```bash
python scripts/eval_extra_trees.py
```

Génère un rapport complet dans `reports/extra-trees-comparison/` : split stratifié, comparaison ET vs XGBoost, 6 plots PNG.

### `scripts/test_predictor.py` — Test unitaire de `pred()`

```bash
python scripts/test_predictor.py
```

---

## 7. Fichiers importants

| Fichier | Rôle |
|---------|------|
| `services/ml-service/src/lora_ml_predict/predictor.py` | **Module d'inférence** — `pred(lat, lon)` → RSSI |
| `services/ml-service/src/lora_ml_predict/app.py` | Service FastAPI existant (encore sur l'ancien modèle) |
| `services/ml-service/data/extra_trees_model.joblib` | Pipeline sklearn entraînée (~90 MB) |
| `services/ml-service/data/terrain_fallback.json` | Fallbacks pour les features terrain |
| `reports/extra-trees-comparison/summary.txt` | Résumé des métriques d'évaluation |
| `reports/extra-trees-comparison/06_comparison_et_vs_xgb.png` | Plot de comparaison ET vs XGBoost |

---

## 8. Comparaison détaillée

### Extra Trees vs XGBoost (mêmes 21 features, même cible RSSI)

```
                              Extra Trees    XGBoost
Test RMSE (dBm)               3.50           3.80
Test MAE (dBm)                2.03           2.18
Test R²                       0.8955         0.8765
```

Extra Trees est **0.30 dB meilleur** que XGBoost sur les mêmes données. L'écart avec l'ancien modèle (~10 dBm) est bien plus grand car l'ancien modèle utilisait seulement 8 features et prédisait des résidus.

### Par bin de distance

*(Voir le plot `06_comparison_et_vs_xgb.png` dans `reports/extra-trees-comparison/` pour le détail par bin de distance.)*

---

## 9. Adapter le service FastAPI (`app.py`)

Si vous utilisez le endpoint `/predict-rssi` existant, voici comment le modifier :

```python
# Dans services/ml-service/src/lora_ml_predict/app.py

# ❌ AVANT (ancien chargement XGBoost)
import joblib
model = joblib.load(settings.model_path)

@app.post("/predict-rssi")
async def predict_rssi(target: TargetPayload):
    features = compute_8_features(target.lat, target.lon, ...)
    return {"rssi_dbm": model.predict(features)[0]}

# ✅ APRÈS (nouveau modèle Extra Trees)
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

> **Note :** Le nouveau module `predictor.py` utilise un chemin dur (`services/ml-service/data/extra_trees_model.joblib`). Pas besoin de variable d'environnement `LORA_ML_MODEL_PATH`.

---

## 10. Limitations à connaître

1. **Features terrain en fallback** — Les features comme `slope`, `roughness`, `fresnel_obstruction_ratio` utilisent des moyennes du dataset. Pas de DEM temps réel.
2. **Zone géographique** — Entraîné sur Da Nang + Hai Phong. Moins fiable ailleurs.
3. **Taille du modèle** — ~90 MB (1500 arbres). Prévoir pour le déploiement.
4. **Gateway automatique** — `pred()` trouve la gateway la plus proche. Pour une gateway spécifique, utiliser `pred_with_gateway()`.
5. **Pas de normalisation SF/fréquence** — Le spreading factor (SF 7-12) est utilisé directement comme feature numérique sans normalisation (normal pour un modèle arborescent). La fréquence est déterminée automatiquement par la gateway sélectionnée.

---

## 11. Checklist de migration

- [ ] Installer les dépendances : `pip install scikit-learn pandas joblib`
- [ ] Installer le package : `pip install -e services/ml-service`
- [ ] Lancer l'entraînement : `python scripts/train_extra_trees.py`
- [ ] Tester : `python scripts/test_predictor.py`
- [ ] Smoke test :

```bash
python -c "from lora_ml_predict.predictor import pred; print(f'Da Nang: {pred(16.06, 108.22):.2f} dBm')"
```

- [ ] Remplacer l'ancien code :

```python
# ANCIEN (25+ lignes, Stage 1 ITU + XGBoost résidu)
residual = predict_residual(lat, lon, sf, freq, gw_obj)
rssi = stage1_pred + residual

# NOUVEAU (1 ligne, Extra Trees RSSI direct)
rssi = pred(lat, lon, spreading_factor=sf)
```

- [ ] Adapter le endpoint FastAPI si nécessaire (voir section 9)
- [ ] Vérifier les métriques : `cat reports/extra-trees-comparison/summary.txt`

---

> **Contact :** Voir `reports/extra-trees-comparison/` pour le rapport complet, ou `scripts/eval_extra_trees.py` pour reproduire l'évaluation.
