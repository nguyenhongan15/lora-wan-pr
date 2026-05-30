#!/usr/bin/env bash
# Wrapper retrain Stage 2 XGBoost residual model.
#
# Flow:
#   1. Tính ordinal kế tiếp → reports/<first|second|...>-train/.
#   2. Copy train script vào container api-service.
#   3. Train trong container (default: refresh cache để dùng data DB mới nhất).
#   4. Fetch joblib + 5 biểu đồ + log về reports/<ordinal>-train/.
#   5. KHÔNG auto-deploy — in copy-paste lệnh để swap thủ công sau khi review.
#
# Usage:
#   bash scripts/retrain_stage2.sh                # data mới: re-compute Stage 1
#   bash scripts/retrain_stage2.sh --use-cache    # dev mode: reuse cache
#   bash scripts/retrain_stage2.sh --container lora-wan-api

set -euo pipefail

CONTAINER="${CONTAINER:-lora-wan-api}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORTS_DIR="$REPO_ROOT/reports"
USE_CACHE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --use-cache)  USE_CACHE=1; shift ;;
        --container)  CONTAINER="$2"; shift 2 ;;
        -h|--help)    sed -n '2,14p' "$0"; exit 0 ;;
        *)            echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

ORDINALS=(first second third fourth fifth sixth seventh eighth ninth tenth
          eleventh twelfth thirteenth fourteenth fifteenth sixteenth
          seventeenth eighteenth nineteenth twentieth)

to_win_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    else
        echo "$1"
    fi
}

mkdir -p "$REPORTS_DIR"
COUNT=$(find "$REPORTS_DIR" -maxdepth 1 -type d -name "*-train" | wc -l)
COUNT=$((COUNT + 1))
if (( COUNT <= 20 )); then
    SLUG="${ORDINALS[$((COUNT - 1))]}-train"
else
    SLUG="${COUNT}-train"
fi
OUT_DIR="$REPORTS_DIR/$SLUG"

if [[ -d "$OUT_DIR" ]]; then
    echo "ERR: $OUT_DIR đã tồn tại" >&2
    exit 1
fi
mkdir -p "$OUT_DIR"

cleanup_empty_outdir() {
    if [[ -d "$OUT_DIR" && -z "$(ls -A "$OUT_DIR" 2>/dev/null)" ]]; then
        rmdir "$OUT_DIR" 2>/dev/null || true
    fi
}
trap cleanup_empty_outdir EXIT

# Bypass Git-Bash path mangling cho docker exec/cp.
export MSYS_NO_PATHCONV=1

if ! docker exec "$CONTAINER" /install/bin/python -c "import matplotlib" 2>/dev/null; then
    echo "▶ Cài matplotlib vào /install/bin/python (one-time)"
    docker exec -u 0 "$CONTAINER" /install/bin/python -m pip install --no-cache-dir matplotlib
fi

CACHE_FILE_IN_CONTAINER="/tmp/stage2_variants_cache.npz"
if (( USE_CACHE == 0 )); then
    echo "▶ Invalidate cache → ép re-compute Stage 1 từ DB"
    docker exec "$CONTAINER" rm -f "$CACHE_FILE_IN_CONTAINER" 2>/dev/null || true
else
    echo "▶ --use-cache: giữ nguyên cache hiện có"
fi

echo "▶ Output: $OUT_DIR"
echo "▶ Copy train script → $CONTAINER:/tmp/train.py"
docker cp "$(to_win_path "$REPO_ROOT/scripts/train_residual_model.py")" "$CONTAINER:/tmp/train.py"

ARTIFACT_IN_CONTAINER="/tmp/stage2_xgb_${SLUG}.joblib"
PLOTS_IN_CONTAINER="/tmp/stage2_plots_${SLUG}"

echo "▶ Train (cache file sẽ tự sinh lại nếu thiếu)..."
docker exec "$CONTAINER" python /tmp/train.py \
    --cache-path "$CACHE_FILE_IN_CONTAINER" \
    --output-path "$ARTIFACT_IN_CONTAINER" \
    --plot-dir "$PLOTS_IN_CONTAINER" 2>&1 | tee "$OUT_DIR/train.log"

echo "▶ Fetch artifact + biểu đồ → $OUT_DIR"
docker cp "$CONTAINER:$ARTIFACT_IN_CONTAINER" "$(to_win_path "$OUT_DIR/stage2_xgb.joblib")"
docker cp "$CONTAINER:$PLOTS_IN_CONTAINER/." "$(to_win_path "$OUT_DIR")"

docker exec "$CONTAINER" rm -rf "$ARTIFACT_IN_CONTAINER" "$PLOTS_IN_CONTAINER" 2>/dev/null || true

JOBLIB_SIZE=$(du -h "$OUT_DIR/stage2_xgb.joblib" | cut -f1)

echo ""
echo "✅ Done: reports/$SLUG/"
echo "   stage2_xgb.joblib  ($JOBLIB_SIZE)"
echo "   01_learning_curve.png  02_pred_vs_meas.png"
echo "   03_error_vs_distance.png  04_per_bin.png  05_feature_importance.png"
echo "   train.log"
echo ""
echo "Review biểu đồ rồi deploy nếu hài lòng:"
echo "   cp reports/$SLUG/stage2_xgb.joblib services/ml-service/data/stage2_xgb.joblib"
echo "   docker compose restart ml-service"
