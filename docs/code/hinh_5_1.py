"""Hinh 5.1 - So do khoi quy trinh xay dung mo hinh hoc may (2D).

4 khoi chinh theo trinh tu doc:
  Co so du lieu -> Tien xu ly + Phan tang -> Huan luyen Extra Trees -> Trien khai
Moi khoi co ghi chu tieng Viet.

Output: docs/anh/hinh_5_1.png
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "anh" / "hinh_5_1.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]

FILL = "#D9E2F3"
BORDER = "#1a3a72"
SUB = "#EAF3DA"

fig, ax = plt.subplots(figsize=(11, 10))
ax.set_xlim(0, 11)
ax.set_ylim(0, 12)
ax.set_aspect("equal")
ax.set_axis_off()


def block(cx, cy, w, h, title, sub, *, fill=FILL):
    x, y = cx - w / 2, cy - h / 2
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.05", facecolor=fill, edgecolor=BORDER, linewidth=1.8
        )
    )
    ax.text(
        cx, cy + 0.45, title, ha="center", va="center", fontsize=13, weight="bold", color=BORDER
    )
    ax.text(cx, cy - 0.55, sub, ha="center", va="center", fontsize=10.5, color="#222")


def arrow(p1, p2, label=None):
    ax.add_patch(
        FancyArrowPatch(p1, p2, arrowstyle="->", mutation_scale=22, linewidth=2, color=BORDER)
    )
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        ax.text(
            mx + 0.25,
            my,
            label,
            fontsize=10,
            color="#555",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": SUB, "edgecolor": "none"},
        )


CX = 5.5
block(
    CX,
    10.5,
    7.5,
    1.4,
    "1. Cơ sở dữ liệu khảo sát",
    "Bảng ts.survey_training — 14 017 mẫu, 21 đặc trưng",
)
block(
    CX,
    7.8,
    7.5,
    1.4,
    "2. Tiền xử lý và phân tầng dữ liệu",
    "Ô lưới H3 res 8 + Phiên 1 giờ — Tỷ lệ 70 / 15 / 15",
)
block(
    CX, 5.1, 7.5, 1.4, "3. Huấn luyện Extra Trees", "1500 cây — độ sâu tối đa 20 — tối ưu song song"
)
block(
    CX,
    2.4,
    7.5,
    1.4,
    "4. Triển khai và phục vụ",
    "Đóng gói joblib — Kích hoạt lại nóng — API dự đoán",
)

arrow((CX, 10.5 - 0.7), (CX, 7.8 + 0.7), "Trích xuất CSV huấn luyện")
arrow((CX, 7.8 - 0.7), (CX, 5.1 + 0.7), "Tập huấn luyện / xác thực / kiểm thử")
arrow((CX, 5.1 - 0.7), (CX, 2.4 + 0.7), "Mô hình đã lưu")

plt.tight_layout()
plt.savefig(OUT, dpi=180, bbox_inches="tight")
print(f"Saved: {OUT}")
