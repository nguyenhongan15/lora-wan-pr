"""
services/report_pdf.py — Sinh PDF report cho Persona 3 (manager / decision maker).

Dùng reportlab — pure Python, không cần Chrome headless.
Layout: bìa → tổng quan campaign → coverage distribution → metrics ML → ghi chú.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ── Font Unicode (DejaVu) — đảm bảo render tiếng Việt ───────────────────────
# Container Ubuntu24 đã có sẵn DejaVu trong /usr/share/fonts/truetype/dejavu/
_FONT_REGISTERED = False

def _ensure_font() -> str:
    """Register DejaVu nếu có; fallback Helvetica nếu không (chữ thường vẫn ok)."""
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return "DejaVu"
    try:
        pdfmetrics.registerFont(TTFont(
            "DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ))
        pdfmetrics.registerFont(TTFont(
            "DejaVu-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ))
        _FONT_REGISTERED = True
        return "DejaVu"
    except Exception:
        return "Helvetica"


def _fmt(v, suffix: str = "", digits: int = 2) -> str:
    if v is None: return "—"
    try:
        return f"{float(v):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return str(v)


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def generate_campaign_report(
    *,
    campaign:    dict,
    stats:       dict,
    coverage:    dict | None,
    grid_status: dict | None,
    gateways:    list[dict],
) -> bytes:
    """
    campaign:   {id, name, environmentType, startDate, endDate, weatherCondition}
    stats:      {total, avgRssi, minRssi, maxRssi, avgSnr}
    coverage:   {strong,medium,weak,veryWeak,strongPct,...} từ scenarios._coverage_dist
    grid_status: kết quả từ /predict/status (avgUncertainty etc.) hoặc None
    gateways:   list dict gateway thuộc campaign
    """
    font     = _ensure_font()
    bold     = f"{font}-Bold" if font == "DejaVu" else "Helvetica-Bold"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
        title=f"LoRa Coverage Report — {campaign.get('name', '')}",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName=bold, fontSize=18,
                         spaceAfter=12, textColor=colors.HexColor("#1e293b"))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=bold, fontSize=13,
                         spaceBefore=14, spaceAfter=8, textColor=colors.HexColor("#334155"))
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName=font, fontSize=10,
                           leading=14, textColor=colors.HexColor("#0f172a"))
    muted = ParagraphStyle("muted", parent=body, fontSize=9,
                            textColor=colors.HexColor("#64748b"))

    story = []

    # ── Bìa ─────────────────────────────────────────────────────
    story.append(Paragraph("BÁO CÁO PHÂN TÍCH PHỦ SÓNG LoRaWAN", h1))
    story.append(Paragraph(campaign.get("name", "—"), h2))
    story.append(Paragraph(
        f"Ngày tạo: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        muted,
    ))
    story.append(Spacer(1, 12))

    # ── Tổng quan campaign ──────────────────────────────────────
    story.append(Paragraph("1. Tổng quan chiến dịch", h2))
    info_rows = [
        ["Tên",           campaign.get("name", "—")],
        ["Môi trường",    campaign.get("environmentType") or "—"],
        ["Bắt đầu",       campaign.get("startDate") or "—"],
        ["Kết thúc",      campaign.get("endDate")   or "—"],
        ["Thời tiết",     campaign.get("weatherCondition") or "—"],
        ["Số gateway",    str(len(gateways))],
    ]
    story.append(_kv_table(info_rows, font, bold))

    # ── Stats RSSI ──────────────────────────────────────────────
    story.append(Paragraph("2. Thống kê RSSI / SNR", h2))
    stats_rows = [
        ["Tổng điểm đo",      str(stats.get("total", 0))],
        ["RSSI trung bình",   _fmt(stats.get("avgRssi"), " dBm")],
        ["RSSI mạnh nhất",    _fmt(stats.get("maxRssi"), " dBm")],
        ["RSSI yếu nhất",     _fmt(stats.get("minRssi"), " dBm")],
        ["SNR trung bình",    _fmt(stats.get("avgSnr"),  " dB")],
    ]
    story.append(_kv_table(stats_rows, font, bold))

    # ── Coverage distribution ───────────────────────────────────
    if coverage and coverage.get("total", 0) > 0:
        story.append(Paragraph("3. Phân bố vùng phủ (LoRa Alliance CVT)", h2))
        cov_rows = [
            ["Mức",                              "Số điểm", "Tỉ lệ"],
            ["Mạnh (≥ −90 dBm)",                 str(coverage["strong"]),
                                                  f"{coverage['strongPct']}%"],
            ["Trung bình (−90 ~ −105 dBm)",      str(coverage["medium"]),
                                                  f"{coverage['mediumPct']}%"],
            ["Yếu (−105 ~ −120 dBm)",            str(coverage["weak"]),
                                                  f"{coverage['weakPct']}%"],
            ["Rất yếu (< −120 dBm)",             str(coverage["veryWeak"]),
                                                  f"{coverage['veryWeakPct']}%"],
        ]
        story.append(_data_table(cov_rows, font, bold))

    # ── ML grid status ──────────────────────────────────────────
    if grid_status and grid_status.get("hasGrid"):
        story.append(Paragraph("4. Kết quả dự đoán ML", h2))
        ml_rows = [
            ["Số điểm lưới",         str(grid_status.get("totalPoints", 0))],
            ["RSSI dự đoán TB",      _fmt(grid_status.get("avgRssiDbm"),       " dBm")],
            ["RSSI dự đoán Min",     _fmt(grid_status.get("minRssiDbm"),       " dBm")],
            ["RSSI dự đoán Max",     _fmt(grid_status.get("maxRssiDbm"),       " dBm")],
            ["Độ không chắc TB",     _fmt(grid_status.get("avgUncertaintyDb"), " dB")],
            ["Lần chạy cuối",        str(grid_status.get("lastGenerated", "—"))],
        ]
        story.append(_kv_table(ml_rows, font, bold))

    # ── Gateway list ────────────────────────────────────────────
    if gateways:
        story.append(PageBreak())
        story.append(Paragraph("5. Danh sách Gateway", h2))
        gw_rows = [["Tên", "EUI", "Vĩ độ", "Kinh độ", "Cao (m)"]]
        for g in gateways:
            gw_rows.append([
                g.get("name") or "—",
                g.get("gatewayEui", ""),
                _fmt(g.get("latitude"),  digits=5),
                _fmt(g.get("longitude"), digits=5),
                _fmt(g.get("altitudeM"), digits=1),
            ])
        story.append(_data_table(gw_rows, font, bold, col_widths=[4*cm, 4*cm, 3*cm, 3*cm, 2*cm]))

    # ── Footer note ────────────────────────────────────────────
    story.append(Spacer(1, 18))
    story.append(Paragraph(
        "Ngưỡng phân loại RSSI tuân theo LoRa Alliance Coverage Verification Test.",
        muted,
    ))

    doc.build(story)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _kv_table(rows, font, bold):
    """2-column key/value table."""
    t = Table(rows, colWidths=[5*cm, 11*cm])
    t.setStyle(TableStyle([
        ("FONT",        (0, 0), (-1, -1), font, 10),
        ("FONT",        (0, 0), (0, -1),  bold, 10),
        ("TEXTCOLOR",   (0, 0), (0, -1),  colors.HexColor("#475569")),
        ("BACKGROUND",  (0, 0), (0, -1),  colors.HexColor("#f1f5f9")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("LINEBELOW",   (0, 0), (-1, -1),  0.4, colors.HexColor("#e2e8f0")),
    ]))
    return t


def _data_table(rows, font, bold, col_widths=None):
    """Data table — header row đậm, viền đầy đủ."""
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("FONT",        (0, 0), (-1, 0),  bold, 10),
        ("FONT",        (0, 1), (-1, -1), font, 10),
        ("BACKGROUND",  (0, 0), (-1, 0),  colors.HexColor("#534AB7")),
        ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
        ("GRID",        (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
    ]))
    return t