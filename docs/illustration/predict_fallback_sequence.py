"""Sơ đồ trình tự /predict + cơ chế fallback mềm (Stage 2 down → Stage 1 only)."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

OUT = Path(__file__).resolve().parents[1] / "illustrationpic" / "predict_fallback_sequence.png"

plt.rcParams.update({"font.family": "DejaVu Sans"})

CLIENT_X = 9
API_X = 32
ML_X = 56

C_CLIENT = "#37474f"
C_API = "#1565c0"
C_ML = "#7b1fa2"
C_SUCCESS = "#2e7d32"
C_FALLBACK = "#e65100"
C_ALT_EDGE = "#888"
C_CALLOUT_EDGE = "#1565c0"
C_CALLOUT_BG = "#e3f2fd"


def draw_actor(ax, x, y_top, label, color):
    box = FancyBboxPatch(
        (x - 8, y_top - 5),
        16,
        5,
        boxstyle="round,pad=0.2,rounding_size=0.3",
        linewidth=1.8,
        edgecolor=color,
        facecolor="white",
    )
    ax.add_patch(box)
    ax.text(
        x, y_top - 2.5, label, ha="center", va="center", fontsize=10.5, weight="bold", color=color
    )


def draw_lifeline(ax, x, y_top, y_bot, color):
    ax.plot([x, x], [y_top, y_bot], color=color, linewidth=1.0, linestyle=":", alpha=0.7)


def draw_arrow(
    ax,
    x_from,
    x_to,
    y,
    label,
    color="black",
    style="-|>",
    label_offset=0.9,
    dashed=False,
    label_color=None,
):
    arr_kwargs = {"arrowstyle": style, "mutation_scale": 18, "linewidth": 1.8, "color": color}
    if dashed:
        arr_kwargs["linestyle"] = "--"
    ax.add_patch(FancyArrowPatch((x_from, y), (x_to, y), **arr_kwargs))
    ax.text(
        (x_from + x_to) / 2,
        y + label_offset,
        label,
        ha="center",
        va="bottom",
        fontsize=9.5,
        color=label_color or color,
        weight="bold",
    )


def draw_self_action(ax, x_lifeline, y, label, color, width=22, height=4):
    box = FancyBboxPatch(
        (x_lifeline + 0.6, y - height / 2),
        width,
        height,
        boxstyle="round,pad=0.15,rounding_size=0.3",
        linewidth=1.3,
        edgecolor=color,
        facecolor="#f8f8f8",
    )
    ax.add_patch(box)
    ax.text(
        x_lifeline + 0.6 + width / 2, y, label, ha="center", va="center", fontsize=9, color=color
    )
    loop = FancyArrowPatch(
        (x_lifeline, y + 0.8),
        (x_lifeline + 0.6, y),
        arrowstyle="-|>",
        mutation_scale=12,
        linewidth=1.2,
        color=color,
        connectionstyle="arc3,rad=-0.4",
    )
    ax.add_patch(loop)


def draw_alt_frame(ax, x0, x1, y_top, y_bot):
    ax.add_patch(
        Rectangle(
            (x0, y_bot),
            x1 - x0,
            y_top - y_bot,
            facecolor="none",
            edgecolor=C_ALT_EDGE,
            linewidth=1.4,
        )
    )
    tab = FancyBboxPatch(
        (x0, y_top - 3.5),
        6,
        3.5,
        boxstyle="square,pad=0",
        linewidth=1.4,
        edgecolor=C_ALT_EDGE,
        facecolor="white",
    )
    ax.add_patch(tab)
    ax.text(
        x0 + 3,
        y_top - 1.75,
        "alt",
        ha="center",
        va="center",
        fontsize=10.5,
        weight="bold",
        color="#444",
    )


def draw_branch_guard(ax, x, y, text, color):
    ax.text(
        x,
        y,
        text,
        ha="left",
        va="center",
        fontsize=9.5,
        weight="bold",
        color=color,
        bbox={
            "boxstyle": "round,pad=0.25",
            "facecolor": "#e8f5e9" if color == C_SUCCESS else "#fff3e0",
            "edgecolor": color,
            "linewidth": 1.2,
        },
    )


def draw_incident_matrix(ax):
    x0, x1 = 70, 99
    y0, y1 = 32, 87
    panel = FancyBboxPatch(
        (x0, y0),
        x1 - x0,
        y1 - y0,
        boxstyle="round,pad=0.3,rounding_size=0.5",
        linewidth=1.3,
        edgecolor="#555",
        facecolor="#fcfcfc",
    )
    ax.add_patch(panel)

    ax.text(
        (x0 + x1) / 2,
        y1 - 3,
        "Ma trận sự cố — kết quả phía Client",
        ha="center",
        va="center",
        fontsize=11,
        weight="bold",
    )
    ax.plot([x0 + 1.5, x1 - 1.5], [y1 - 6, y1 - 6], color="#888", linewidth=0.8)

    rows = [
        ("Timeout (>0,5 s)", "200 — Stage 1", C_FALLBACK),
        ("Model chưa load (503)", "200 — Stage 1", C_FALLBACK),
        ("Inference lỗi (500)", "200 — Stage 1", C_FALLBACK),
        ("Sai token (401)", "200 — Stage 1", C_FALLBACK),
        ("OOD (200 + null)", "200 — Stage 1", C_FALLBACK),
        ("Thành công (200)", "200 — Stage 1 + 2", C_SUCCESS),
    ]

    header_y = y1 - 9.5
    ax.text(x0 + 2, header_y, "Tình huống", fontsize=9.5, weight="bold", color="#222")
    ax.text(x0 + 16, header_y, "Trả về Client", fontsize=9.5, weight="bold", color="#222")
    ax.plot([x0 + 1.5, x1 - 1.5], [header_y - 1.5, header_y - 1.5], color="#888", linewidth=0.8)

    row_y = header_y - 4
    for situation, result, color in rows:
        ax.text(x0 + 2, row_y, situation, fontsize=9, color="#222")
        ax.text(x0 + 16, row_y, result, fontsize=9, color=color, weight="bold")
        row_y -= 4.5

    ax.text(
        (x0 + x1) / 2,
        y0 + 2.5,
        "Không bao giờ expose 5xx ra Client",
        ha="center",
        fontsize=9,
        style="italic",
        color="#c62828",
        weight="bold",
    )


def main():
    fig, ax = plt.subplots(figsize=(17, 12))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_aspect("auto")
    ax.axis("off")

    ax.text(
        50,
        98,
        "Luồng /coverage/predict — Stage 1 luôn chạy, Stage 2 fallback mềm",
        ha="center",
        fontsize=14.5,
        weight="bold",
    )
    ax.text(
        50,
        95,
        "Sơ đồ trình tự 3-lifeline + ma trận sự cố",
        ha="center",
        fontsize=10.5,
        style="italic",
        color="#555",
    )

    y_actor_top = 92
    y_lifeline_top = 87
    y_lifeline_bot = 11

    draw_actor(ax, CLIENT_X, y_actor_top, "Client\n(web-app / user)", C_CLIENT)
    draw_actor(ax, API_X, y_actor_top, "api-service\n(Tầng 1 + Stage2Client)", C_API)
    draw_actor(ax, ML_X, y_actor_top, "ml-service\n(Tầng 2 XGBoost)", C_ML)
    draw_lifeline(ax, CLIENT_X, y_lifeline_top, y_lifeline_bot, C_CLIENT)
    draw_lifeline(ax, API_X, y_lifeline_top, y_lifeline_bot, C_API)
    draw_lifeline(ax, ML_X, y_lifeline_top, y_lifeline_bot, C_ML)

    note_cx, note_cy = 82, 89.5
    ax.text(
        note_cx,
        note_cy,
        "GET /healthz + check_model_active\n→ trả 503 sớm, tránh timeout vô ích",
        ha="center",
        va="center",
        fontsize=8.5,
        color="#555",
        style="italic",
        bbox={
            "boxstyle": "round,pad=0.3",
            "facecolor": "#fffde7",
            "edgecolor": "#fbc02d",
            "linewidth": 1.0,
        },
    )
    ax.plot(
        [ML_X + 8, note_cx - 5.5], [note_cy, note_cy], color="#fbc02d", linestyle=":", linewidth=1.1
    )

    draw_arrow(ax, CLIENT_X, API_X, 84, "POST /api/v1/coverage/predict", "black")

    draw_self_action(
        ax,
        API_X,
        78,
        "Tầng 1 (ITU-R P.1812 + DSM):\nsinh Prediction RSSI/SNR/margin/SF",
        color=C_API,
        width=24,
        height=5,
    )

    draw_arrow(ax, API_X, ML_X, 70, "POST /residual   (Bearer token, timeout 0,5 s)", "black")

    alt_x0, alt_x1 = 4, 67
    alt_top, alt_bot = 65, 14
    draw_alt_frame(ax, alt_x0, alt_x1, alt_top, alt_bot)

    y_succ_guard = 62
    draw_branch_guard(ax, alt_x0 + 8, y_succ_guard, "[ ml-service trả 200 OK ]", C_SUCCESS)

    draw_arrow(
        ax,
        ML_X,
        API_X,
        57,
        "200  { residual_db: X }",
        C_SUCCESS,
        style="-|>",
        label_offset=1.0,
        dashed=True,
    )

    draw_self_action(
        ax,
        API_X,
        50,
        "RSSI += X\nmodel_version = stage1-itu-p1812-v0.1.0\n+ stage2-xgb-v0.6.0",
        color=C_SUCCESS,
        width=30,
        height=6,
    )

    draw_arrow(
        ax,
        API_X,
        CLIENT_X,
        40,
        "200 OK  { Prediction }  — Stage 1 + Stage 2",
        C_SUCCESS,
        label_offset=1.0,
        dashed=True,
    )

    ax.plot([alt_x0 + 1, alt_x1 - 1], [35, 35], color=C_ALT_EDGE, linewidth=1.2, linestyle="--")
    ax.text(
        alt_x0 + 2,
        35,
        "  else  ",
        ha="left",
        va="center",
        fontsize=10,
        color="#666",
        style="italic",
        bbox={"boxstyle": "round,pad=0.2", "facecolor": "white", "edgecolor": "#888"},
    )

    draw_branch_guard(ax, alt_x0 + 8, 32, "[ timeout / 503 / 500 / 401 / OOD ]", C_FALLBACK)

    draw_self_action(
        ax,
        API_X,
        26,
        "fallback im lặng → Stage 1 only\nmodel_version = stage1-itu-p1812-v0.1.0",
        color=C_FALLBACK,
        width=30,
        height=5.5,
    )

    draw_arrow(
        ax,
        API_X,
        CLIENT_X,
        19,
        "200 OK  { Prediction }  — Stage 1 only  (KHÔNG expose 5xx)",
        C_FALLBACK,
        label_offset=1.0,
        dashed=True,
    )

    draw_incident_matrix(ax)

    callout = FancyBboxPatch(
        (4, 2.5),
        95,
        6.5,
        boxstyle="round,pad=0.3,rounding_size=0.6",
        linewidth=2.0,
        edgecolor=C_CALLOUT_EDGE,
        facecolor=C_CALLOUT_BG,
    )
    ax.add_patch(callout)
    ax.text(
        50,
        6.7,
        "★  Không có single point of failure",
        ha="center",
        va="center",
        fontsize=13,
        weight="bold",
        color="#0a3a78",
    )
    ax.text(
        50,
        4.0,
        "ml-service hỏng → độ chính xác giảm, dịch vụ vẫn phục vụ (Stage 1 đảm bảo).",
        ha="center",
        va="center",
        fontsize=10.5,
        color="#0a3a78",
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=180, bbox_inches="tight", facecolor="white")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
