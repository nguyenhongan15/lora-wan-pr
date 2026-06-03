"""Pipeline huấn luyện 6 bước — Stage 2 ML residual (XGBoost v0.4-lock)."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "illustrationpic" / "training_pipeline_6steps.png"

plt.rcParams.update({"font.family": "DejaVu Sans"})

C_BOX = "#dbe9ff"
C_BOX_EDGE = "#1565c0"
C_HL_BG = "#fff3e0"
C_HL_EDGE = "#e65100"
C_ARROW = "#444"
C_PANEL_BG = "#fafafa"
C_PANEL_EDGE = "#555"
C_CALL_BG = "#fff5f5"
C_CALL_EDGE = "#c62828"

STEPS = [
    {
        "title": "1. Truy vấn dữ liệu",
        "body": "Join ts.survey_training\n⋈ geo.gateways\nlọc d < 50 km\n(loại lỗi ETL\nHải Phòng–Đà Nẵng)",
    },
    {
        "title": "2. Tách theo thời gian",
        "body": "Train+Val:\nngẫu nhiên 11–12/2025\n────────\nHold-out:\n1–2/2026",
        "highlight": True,
    },
    {
        "title": "3. Tính phần dư",
        "body": "Mỗi dòng:\nStage1ItuModel.predict()\n↓\nresidual =\nRSSI_đo − RSSI_Tầng1",
    },
    {
        "title": "4. Sinh đặc trưng",
        "body": "Dẫn xuất:\n• distance_km\n• log_distance_km\n• delta_alt_m\n→ giữ 8 đặc trưng",
    },
    {
        "title": "5. Chia fold nội bộ",
        "body": "StratifiedKFold(5)\ntheo SF\n────────\nfold 0 = val\ncho early-stopping",
    },
    {
        "title": "6. Huấn luyện & đánh giá",
        "body": "XGBRegressor\n(tree_method='hist')\n↓\nRMSE / MAE / bias\ntrên hold-out",
    },
]

HYPERPARAMS = [
    "n_estimators       = 2000",
    "learning_rate      = 0.05",
    "max_depth          = 4",
    "min_child_weight   = 20",
    "subsample          = 0.7",
    "colsample_bytree   = 0.7",
    "reg_alpha          = 1.0",
    "reg_lambda         = 10.0",
    "early_stopping     = 50",
]


def draw_step_box(ax, cx, cy, w, h, step):
    highlight = step.get("highlight", False)
    bg = C_HL_BG if highlight else C_BOX
    edge = C_HL_EDGE if highlight else C_BOX_EDGE
    lw = 2.6 if highlight else 1.4

    box = FancyBboxPatch(
        (cx - w / 2, cy - h / 2),
        w,
        h,
        boxstyle="round,pad=0.3,rounding_size=0.5",
        linewidth=lw,
        edgecolor=edge,
        facecolor=bg,
    )
    ax.add_patch(box)

    title_y = cy + h / 2 - 2.0
    ax.text(
        cx, title_y, step["title"], ha="center", va="top", fontsize=10.5, weight="bold", color=edge
    )

    ax.plot(
        [cx - w / 2 + 1.0, cx + w / 2 - 1.0],
        [title_y - 3.0, title_y - 3.0],
        color=edge,
        linewidth=0.8,
        alpha=0.6,
    )

    ax.text(cx, cy - 1.5, step["body"], ha="center", va="center", fontsize=8.7, color="#222")


def main():
    fig, ax = plt.subplots(figsize=(16, 9))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_aspect("auto")
    ax.axis("off")

    ax.text(
        50,
        96.5,
        "Pipeline huấn luyện 6 bước — Stage 2 ML residual",
        ha="center",
        fontsize=15,
        weight="bold",
    )
    ax.text(
        50,
        92.5,
        "Từ truy vấn dữ liệu → tách thời gian → phần dư → đặc trưng → fold → huấn luyện & đánh giá",
        ha="center",
        fontsize=10.5,
        color="#555",
        style="italic",
    )

    box_w, box_h = 15.5, 22
    box_y = 73
    centers_x = [9.0, 25.5, 42.0, 58.5, 75.0, 91.5]

    for cx, step in zip(centers_x, STEPS, strict=False):
        draw_step_box(ax, cx, box_y, box_w, box_h, step)

    for i in range(5):
        x_from = centers_x[i] + box_w / 2
        x_to = centers_x[i + 1] - box_w / 2
        arr = FancyArrowPatch(
            (x_from, box_y),
            (x_to, box_y),
            arrowstyle="-|>",
            mutation_scale=22,
            linewidth=2.2,
            color=C_ARROW,
        )
        ax.add_patch(arr)

    panel_x0, panel_x1 = 75, 99
    panel_y0, panel_y1 = 6, 55
    panel = FancyBboxPatch(
        (panel_x0, panel_y0),
        panel_x1 - panel_x0,
        panel_y1 - panel_y0,
        boxstyle="round,pad=0.3,rounding_size=0.5",
        linewidth=1.4,
        edgecolor=C_PANEL_EDGE,
        facecolor=C_PANEL_BG,
    )
    ax.add_patch(panel)

    ax.text(
        (panel_x0 + panel_x1) / 2,
        panel_y1 - 2.5,
        "Siêu tham số v0.4-lock",
        ha="center",
        va="top",
        fontsize=11,
        weight="bold",
    )
    ax.plot(
        [panel_x0 + 2, panel_x1 - 2], [panel_y1 - 6.5, panel_y1 - 6.5], color="#888", linewidth=0.8
    )

    line_y = panel_y1 - 9.5
    for line in HYPERPARAMS:
        ax.text(
            panel_x0 + 2.0,
            line_y,
            line,
            ha="left",
            va="top",
            fontsize=9,
            family="monospace",
            color="#222",
        )
        line_y -= 3.6

    ax.text(
        (panel_x0 + panel_x1) / 2,
        panel_y0 + 2.5,
        "↳ tuned bằng Optuna 100-trial",
        ha="center",
        va="bottom",
        fontsize=9,
        style="italic",
        color="#666",
    )

    arr_down = FancyArrowPatch(
        (centers_x[5], box_y - box_h / 2),
        (centers_x[5], panel_y1),
        arrowstyle="-|>",
        mutation_scale=20,
        linewidth=2.0,
        color=C_ARROW,
    )
    ax.add_patch(arr_down)

    call_x0, call_x1 = 4, 72
    call_y_c = 30
    call_h = 26
    callout = FancyBboxPatch(
        (call_x0, call_y_c - call_h / 2),
        call_x1 - call_x0,
        call_h,
        boxstyle="round,pad=0.4,rounding_size=0.6",
        linewidth=1.6,
        edgecolor=C_CALL_EDGE,
        facecolor=C_CALL_BG,
    )
    ax.add_patch(callout)

    ax.text(
        (call_x0 + call_x1) / 2,
        call_y_c + 10,
        "★  Tinh chỉnh quan trọng (chặn overfit)",
        ha="center",
        va="center",
        fontsize=12,
        weight="bold",
        color=C_CALL_EDGE,
    )

    ax.text(
        (call_x0 + call_x1) / 2,
        call_y_c + 3.5,
        "Siết  min_child_weight  10 → 20   &   reg_lambda  2 → 10\n"
        "để chặn overfit ở bin 2–5 km thưa (chỉ 45 mẫu)",
        ha="center",
        va="center",
        fontsize=10.5,
        color="#333",
    )

    ax.text(
        (call_x0 + call_x1) / 2,
        call_y_c - 5.5,
        "Kết quả trên hold-out:",
        ha="center",
        va="center",
        fontsize=9.5,
        style="italic",
        color="#666",
    )
    ax.text(
        (call_x0 + call_x1) / 2,
        call_y_c - 9.5,
        "RMSE  13,93 → 10,94 dB        bias  +17,94 → +3,18 dB",
        ha="center",
        va="center",
        fontsize=11,
        weight="bold",
        color=C_CALL_EDGE,
    )

    arr_call = FancyArrowPatch(
        (call_x1 + 0.3, call_y_c),
        (panel_x0 - 0.3, call_y_c),
        arrowstyle="-|>",
        mutation_scale=22,
        linewidth=2.2,
        color=C_CALL_EDGE,
    )
    ax.add_patch(arr_call)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=180, bbox_inches="tight", facecolor="white")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
