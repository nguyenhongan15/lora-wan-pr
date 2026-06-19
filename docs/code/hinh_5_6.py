"""Hinh 5.6 - Chuoi 4 buoc huan luyen lai tu dong qua Celery.

Sequence: Admin -> Celery -> [4 buoc script] -> ml-service (hot-reload).
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_5_6.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]

BORDER = "#1a3a72"
FILL = "#D9E2F3"
HIGHLIGHT = "#F4D8A8"
SUB = "#EAF3DA"
GREEN = "#9FCFAE"

fig, ax = plt.subplots(figsize=(14, 8.5))
ax.set_xlim(0, 14)
ax.set_ylim(0, 10)
ax.set_aspect("equal")
ax.set_axis_off()


def block(cx, cy, w, h, title, sub, *, fill=FILL):
    x, y = cx - w / 2, cy - h / 2
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.05", facecolor=fill, edgecolor=BORDER, linewidth=1.6
        )
    )
    ax.text(
        cx, cy + 0.35, title, ha="center", va="center", fontsize=11.5, weight="bold", color=BORDER
    )
    ax.text(cx, cy - 0.42, sub, ha="center", va="center", fontsize=9.5, color="#222")


def arrow(p1, p2, label=None, dashed=False):
    style = "--" if dashed else "-"
    ax.add_patch(
        FancyArrowPatch(
            p1, p2, arrowstyle="->", mutation_scale=18, linewidth=1.8, color=BORDER, linestyle=style
        )
    )
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        ax.text(
            mx,
            my + 0.2,
            label,
            fontsize=9.5,
            color="#444",
            ha="center",
            bbox={"boxstyle": "round,pad=0.2", "facecolor": SUB, "edgecolor": "none"},
        )


# Hang tren - kich hoat
block(2.0, 8.8, 3.0, 1.0, "Quản trị viên", "Bấm nút Huấn luyện lại", fill=HIGHLIGHT)
block(7.0, 8.8, 3.0, 1.0, "Hàng đợi Celery", "Thêm việc + ghi audit", fill=HIGHLIGHT)
block(12.0, 8.8, 3.0, 1.0, "Celery worker", "Tiến trình con tuần tự", fill=HIGHLIGHT)

arrow((2.0 + 1.5, 8.8), (7.0 - 1.5, 8.8), "POST /retrain")
arrow((7.0 + 1.5, 8.8), (12.0 - 1.5, 8.8), "lấy việc")

# Hang giua - 4 buoc
ys = 6.0
w = 3.0
h = 1.3
xs = [1.8, 5.4, 9.0, 12.6]

block(xs[0], ys, w, h, "1. Tạo CSV huấn luyện", "build_training_csv.py\ntối đa 40 phút")
block(xs[1], ys, w, h, "2. Huấn luyện Extra Trees", "train_extra_trees.py\ntối đa 60 phút")
block(xs[2], ys, w, h, "3. Đánh giá tập kiểm thử", "eval_extra_trees_holdout.py\ntối đa 5 phút")
block(xs[3], ys, w, h, "4. Xuất báo cáo", "render_ml_report.py\ntối đa 10 phút")

# Mui ten ngang giua 4 buoc
for i in range(3):
    arrow((xs[i] + w / 2, ys), (xs[i + 1] - w / 2, ys))

# Mui ten tu Celery worker xuong buoc 1
arrow((12.0, 8.8 - 0.5), (xs[0], ys + h / 2 + 0.5), label="kích hoạt", dashed=False)

# Atomic swap dau ra buoc 2
ax.text(
    xs[1],
    ys - 1.2,
    "Đổi tên nguyên tử\n.new → .joblib",
    ha="center",
    fontsize=9.5,
    color="#a8761a",
    style="italic",
    bbox={
        "boxstyle": "round,pad=0.25",
        "facecolor": "#FBF1DE",
        "edgecolor": "#a8761a",
        "linewidth": 0.8,
    },
)

# Hang duoi - hot-reload + audit
block(
    4.0,
    2.5,
    4.0,
    1.3,
    "Kích hoạt lại nóng",
    "ml-service /admin/reload\nNạp lại mô hình joblib",
    fill=GREEN,
)
block(
    10.0,
    2.5,
    4.0,
    1.3,
    "Cập nhật audit log",
    "audit.ml_retrain_jobs\nstatus, metrics, người gọi",
    fill=GREEN,
)

# Mui ten tu buoc 2 xuong hot-reload
arrow((xs[1], ys - h / 2), (4.0, 2.5 + 0.7), label="POST + Bearer token")
# Mui ten tu buoc 4 xuong audit
arrow((xs[3], ys - h / 2), (10.0, 2.5 + 0.7), label="ghi báo cáo")

# Fail-soft note
ax.text(
    7.0,
    0.7,
    "Nếu kích hoạt lại nóng thất bại → ghi cảnh báo, "
    "mô hình cũ tiếp tục phục vụ — không hỏng hệ thống",
    ha="center",
    fontsize=10,
    color="#555",
    style="italic",
)

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
