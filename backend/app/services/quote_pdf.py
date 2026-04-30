"""Customer-facing quote PDF.

Produces a clean, branded one-to-three page document the retailer can
print or email to a customer. Distinct from pdf_generator (program
bulletins are dealer-internal documents); this is shareable as-is and
intentionally omits internal-only fields like stacking-matrix detail
or per-program admin notes.

Detail levels (caller picks):
  • summary  — vehicle hero + final monthly/total only (1 page)
  • standard — adds the dealer pricing breakdown (1-2 pages)
  • detailed — adds program list + APR/lease term info + every line
    item the calculator showed (2-3 pages)
"""

import os
from datetime import datetime
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable,
)


# Same INEOS palette as pdf_generator so the customer doc reads as
# part of the brand system.
ONYX = colors.HexColor("#1D1D1D")
FLARE_RED = colors.HexColor("#FF4639")
MUSHROOM = colors.HexColor("#D9D7D0")
MUSHROOM_LIGHT = colors.HexColor("#FAFAF9")
DOVE = colors.HexColor("#E9E8E5")
IRON_SMOKE = colors.HexColor("#606060")
SILVER_DUST = colors.HexColor("#9F9F9F")
SUCCESS_GREEN = colors.HexColor("#2C931E")
WHITE = colors.white


def _styles() -> dict:
    s = {}
    s["title"] = ParagraphStyle(
        "title", fontSize=22, fontName="Helvetica-Bold", textColor=WHITE,
        leading=26, charSpace=0.6,
    )
    s["subtitle"] = ParagraphStyle(
        "subtitle", fontSize=10, fontName="Helvetica", textColor=colors.HexColor("#BFBFBF"),
        leading=13, charSpace=1.2,
    )
    s["section_heading"] = ParagraphStyle(
        "section_heading", fontSize=11, fontName="Helvetica-Bold", textColor=WHITE,
        leading=14, charSpace=1.5,
    )
    s["body"] = ParagraphStyle(
        "body", fontSize=10.5, fontName="Helvetica", textColor=ONYX,
        leading=14, spaceAfter=4,
    )
    s["body_small"] = ParagraphStyle(
        "body_small", fontSize=9, fontName="Helvetica", textColor=IRON_SMOKE,
        leading=12,
    )
    s["body_strong"] = ParagraphStyle(
        "body_strong", fontSize=11, fontName="Helvetica-Bold", textColor=ONYX,
        leading=14,
    )
    s["meta_label"] = ParagraphStyle(
        "meta_label", fontSize=8, fontName="Helvetica-Bold", textColor=IRON_SMOKE,
        leading=12, charSpace=1.2,
    )
    s["meta_value"] = ParagraphStyle(
        "meta_value", fontSize=10.5, fontName="Helvetica", textColor=ONYX,
        leading=14,
    )
    s["hero_label"] = ParagraphStyle(
        "hero_label", fontSize=8.5, fontName="Helvetica-Bold", textColor=IRON_SMOKE,
        leading=12, charSpace=1.4, alignment=TA_CENTER,
    )
    s["hero_value"] = ParagraphStyle(
        "hero_value", fontSize=34, fontName="Helvetica-Bold", textColor=ONYX,
        leading=38, alignment=TA_CENTER,
    )
    s["hero_sub"] = ParagraphStyle(
        "hero_sub", fontSize=9.5, fontName="Helvetica", textColor=IRON_SMOKE,
        leading=12, alignment=TA_CENTER,
    )
    s["disclaimer"] = ParagraphStyle(
        "disclaimer", fontSize=7.5, fontName="Helvetica", textColor=SILVER_DUST,
        leading=10, alignment=TA_LEFT,
    )
    s["section_label"] = ParagraphStyle(
        "section_label", fontSize=10, fontName="Helvetica-Bold", textColor=ONYX,
        leading=13, charSpace=1.3,
    )
    return s


def _title_bar(title: str, subtitle: str, styles: dict):
    """Onyx title bar — same shape as the program bulletin so the
    customer doc and the dealer doc look like siblings."""
    inner = [
        [Paragraph(title.upper(), styles["title"])],
        [Paragraph(subtitle.upper(), styles["subtitle"])],
    ]
    t = Table(inner, colWidths=[7.0 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ONYX),
        ("LEFTPADDING", (0, 0), (-1, -1), 22),
        ("RIGHTPADDING", (0, 0), (-1, -1), 22),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (-1, 0), 4, FLARE_RED),
    ]))
    return t


def _section_header(label: str, styles: dict):
    inner = [[Paragraph(label.upper(), styles["section_heading"])]]
    t = Table(inner, colWidths=[7.0 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ONYX),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _meta_pair(label: str, value: str, styles: dict):
    return Table(
        [[Paragraph(label.upper(), styles["meta_label"]),
          Paragraph(str(value or "—"), styles["meta_value"])]],
        colWidths=[1.6 * inch, 5.4 * inch],
        style=TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]),
    )


def _hero_block(label: str, value: str, sub: str, styles: dict):
    """Centered headline number with a label above and sub-line below.
    Same visual weight as the on-screen calculator hero so the customer
    sees the familiar number when they print the quote."""
    inner = [
        [Paragraph(label, styles["hero_label"])],
        [Paragraph(value, styles["hero_value"])],
        [Paragraph(sub, styles["hero_sub"])],
    ]
    t = Table(inner, colWidths=[7.0 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), MUSHROOM_LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 18),
        ("RIGHTPADDING", (0, 0), (-1, -1), 18),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    t._argW[0] = 7.0 * inch
    return t


def _money(n) -> str:
    try:
        return f"${float(n):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _money_signed(n) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}"


def _on_page_footer(canvas, doc):
    """Footer painted by the page template so multi-page docs get
    correct page numbers and the brand mark on every page."""
    canvas.saveState()
    page_w, _ = letter
    canvas.setStrokeColor(MUSHROOM)
    canvas.setLineWidth(0.5)
    canvas.line(0.6 * inch, 0.55 * inch, page_w - 0.6 * inch, 0.55 * inch)
    canvas.setFillColor(ONYX)
    canvas.setFont("Helvetica-Bold", 9.5)
    brand = "INEOS  |  GRENADIER"
    text_w = canvas.stringWidth(brand, "Helvetica-Bold", 9.5)
    x = (page_w - text_w) / 2
    canvas.drawString(x, 0.40 * inch, brand)
    prefix = "INEOS  |  GREN"
    a_x = x + canvas.stringWidth(prefix, "Helvetica-Bold", 9.5)
    canvas.setFillColor(FLARE_RED)
    canvas.drawString(a_x, 0.40 * inch, "A")
    canvas.setFillColor(SILVER_DUST)
    canvas.setFont("Helvetica", 7.5)
    footer = f"INEOS Automotive Americas  ·  Generated {datetime.now().strftime('%B %d, %Y')}  ·  Page {doc.page}"
    fw = canvas.stringWidth(footer, "Helvetica", 7.5)
    canvas.drawString((page_w - fw) / 2, 0.27 * inch, footer)
    canvas.restoreState()


def _vehicle_section(deal: dict, styles: dict, detail: str) -> list:
    """Vehicle hero block — VIN, MY/body/trim, MSRP, optionally
    color/dealer at higher detail levels."""
    out = []
    out.append(_section_header("Vehicle", styles))
    out.append(Spacer(1, 8))

    veh = deal.get("vehicle") or {}
    body = (veh.get("body_style") or "").replace("_", " ")
    body_label = "Arcane Works" if veh.get("body_style") == "arcane_works" else body.title()
    my = veh.get("model_year") or ""
    trim = veh.get("trim") or ""
    headline_parts = [my, body_label]
    if trim:
        headline_parts.append(trim)
    headline = " ".join([p for p in headline_parts if p]).strip() or "INEOS Grenadier"
    out.append(Paragraph(f"<b>{headline} INEOS Grenadier</b>", styles["body_strong"]))
    out.append(Spacer(1, 6))
    if veh.get("vin"):
        out.append(_meta_pair("VIN", veh["vin"], styles))
    if veh.get("msrp"):
        out.append(_meta_pair("Base MSRP", _money(veh["msrp"]), styles))

    if detail in ("standard", "detailed"):
        if veh.get("color_exterior"):
            out.append(_meta_pair("Exterior", veh["color_exterior"], styles))
        if veh.get("color_interior"):
            out.append(_meta_pair("Interior", veh["color_interior"], styles))
        if veh.get("dealer_name"):
            out.append(_meta_pair("Retailer", veh["dealer_name"], styles))
    return out


def _programs_section(deal: dict, styles: dict, detail: str) -> list:
    """List of selected incentive programs with amounts. Customer-facing
    so we drop the program_type code in favor of the human name."""
    programs = deal.get("programs") or []
    if not programs:
        return []
    out = [_section_header("Eligible Incentives", styles), Spacer(1, 8)]
    for p in programs:
        name = p.get("name") or "Program"
        amount = p.get("amount") or 0
        line = Table(
            [[Paragraph(name, styles["body"]),
              Paragraph(_money(amount), styles["body_strong"])]],
            colWidths=[5.2 * inch, 1.8 * inch],
            style=TableStyle([
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, DOVE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]),
        )
        out.append(line)
    total = sum(float(p.get("amount") or 0) for p in programs)
    out.append(Spacer(1, 4))
    out.append(Table(
        [[Paragraph("<b>Total Incentive</b>", styles["body_strong"]),
          Paragraph(f"<b>{_money(total)}</b>", styles["body_strong"])]],
        colWidths=[5.2 * inch, 1.8 * inch],
        style=TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LINEABOVE", (0, 0), (-1, -1), 1, ONYX),
        ]),
    ))
    return out


def _pricing_section(deal: dict, styles: dict, detail: str) -> list:
    """Dealer pricing breakdown table. Same line items the on-screen
    calculator shows so the customer recognizes the numbers."""
    lines = deal.get("lines") or []
    if not lines:
        return []
    out = [_section_header("Pricing Breakdown", styles), Spacer(1, 8)]
    rows = [[
        Paragraph("<b>Item</b>", styles["body_strong"]),
        Paragraph("<b>Amount</b>", styles["body_strong"]),
    ]]
    last_idx = len(lines) - 1
    for i, item in enumerate(lines):
        # Each line is [label, amount] from the calculator
        if isinstance(item, dict):
            lbl, amt = item.get("label") or "", item.get("amount") or 0
        else:
            try:
                lbl, amt = item[0], item[1]
            except Exception:
                continue
        is_last = (i == last_idx)
        style = styles["body_strong"] if is_last else styles["body"]
        rows.append([Paragraph(str(lbl), style),
                     Paragraph(_money_signed(amt), style)])
    t = Table(rows, colWidths=[5.2 * inch, 1.8 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), MUSHROOM_LIGHT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, MUSHROOM),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, DOVE),
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, ONYX),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [WHITE, MUSHROOM_LIGHT]),
    ]))
    out.append(t)
    return out


def _terms_section(deal: dict, styles: dict, detail: str) -> list:
    """APR / Lease term details. Only shown at detailed level."""
    if detail != "detailed":
        return []
    deal_type = deal.get("deal_type") or "cash"
    if deal_type == "cash":
        return []
    out = [_section_header("Financing Terms", styles), Spacer(1, 8)]
    if deal_type == "apr":
        out.append(_meta_pair("Term", f"{deal.get('term_finance', '')} months", styles))
        out.append(_meta_pair("APR", f"{deal.get('apr', '')}%", styles))
        out.append(_meta_pair("Lender", deal.get("lender") or "Santander", styles))
    elif deal_type == "lease":
        out.append(_meta_pair("Term", f"{deal.get('term_lease', '')} months", styles))
        out.append(_meta_pair("Annual Mileage", f"{int(float(deal.get('mileage', 10000) or 10000)):,}", styles))
        out.append(_meta_pair("Money Factor", deal.get("money_factor") or "—", styles))
        out.append(_meta_pair("Residual %", f"{deal.get('residual_pct', '')}%", styles))
        out.append(_meta_pair("Lender", deal.get("lender") or "Santander", styles))
    return out


def _disclosure_block(deal: dict, styles: dict) -> list:
    """Standard customer disclosure footer — always included regardless
    of detail level. Generic to cover all deal types."""
    deal_type = deal.get("deal_type") or "cash"
    base = (
        "Pricing shown is an estimate. Final pricing, taxes, title, registration, "
        "and any dealer-installed equipment are confirmed at delivery. Offer "
        "valid on in-stock vehicles only and subject to change without notice. "
        "Additional restrictions may apply."
    )
    extra = ""
    if deal_type == "apr":
        extra = (
            " APR and term subject to credit approval through Santander. Rate "
            "shown reflects Tier 1 credit; your rate may differ. "
        )
    elif deal_type == "lease":
        extra = (
            " Lease subject to credit approval through Santander. Residual "
            "adjusted for the indicated annual mileage. First payment, taxes, "
            "and disposition fee may apply at signing. "
        )
    return [
        Paragraph("Important Disclosures".upper(), styles["section_label"]),
        Spacer(1, 4),
        Paragraph(base + extra, styles["disclaimer"]),
    ]


def _hero_for(deal: dict, styles: dict):
    """Top-of-page hero: monthly payment for finance/lease, net price
    for cash. Always included regardless of detail level."""
    deal_type = deal.get("deal_type") or "cash"
    if deal_type == "cash":
        net = deal.get("net_price") or 0
        sub = "Net price after discount, incentives, and applicable taxes."
        return _hero_block("Net Purchase Price", _money(net), sub, styles)
    monthly = deal.get("monthly") or 0
    if deal_type == "apr":
        sub = (f"Estimated monthly payment · {deal.get('term_finance', '')}-month "
               f"finance @ {deal.get('apr', '')}% APR (Santander)")
    else:
        sub = (f"Estimated monthly payment · {deal.get('term_lease', '')}-month lease · "
               f"{int(float(deal.get('mileage', 10000) or 10000)):,} mi/yr")
    label = "Estimated Monthly Payment"
    val = f"{_money(monthly)}<font size=14 color='#9F9F9F'> /mo</font>"
    return _hero_block(label, val, sub, styles)


def generate_quote_pdf(deal: dict, detail: str = "standard") -> bytes:
    """Generate the PDF and return the bytes. Caller is responsible for
    setting Content-Disposition headers on the FastAPI response.

    deal shape:
      {
        "vehicle": { vin, model_year, body_style, trim, msrp,
                     color_exterior?, color_interior?, dealer_name? },
        "deal_type": "cash" | "apr" | "lease",
        "monthly": float,        # finance / lease only
        "net_price": float,      # cash only
        "term_finance": int,     # apr only
        "apr": float,            # apr only
        "term_lease": int,       # lease only
        "money_factor": str,     # lease only
        "residual_pct": float,   # lease only
        "mileage": int,          # lease only
        "lender": str,           # finance / lease only
        "programs": [{name, amount}, ...],
        "lines": [[label, amount], ...],   # pricing breakdown
        "code": str,             # campaign code (informational only)
        "customer_name": str,    # optional, printed on hero subtitle
      }

    detail: 'summary' | 'standard' | 'detailed'."""
    if detail not in ("summary", "standard", "detailed"):
        detail = "standard"

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.55 * inch, bottomMargin=0.75 * inch,
        title="INEOS Grenadier Quote",
        author="INEOS Automotive Americas",
    )

    styles = _styles()
    story = []

    today = datetime.now().strftime("%B %d, %Y")
    customer = deal.get("customer_name")
    subtitle = f"Personalized Quote · {today}"
    if customer:
        subtitle = f"Prepared for {customer} · {today}"
    story.append(_title_bar("INEOS Grenadier", subtitle, styles))
    story.append(Spacer(1, 16))

    # Hero — always shown
    story.append(_hero_for(deal, styles))
    story.append(Spacer(1, 18))

    # Vehicle — always shown (details vary by level)
    story.extend(_vehicle_section(deal, styles, detail))
    story.append(Spacer(1, 14))

    if detail in ("standard", "detailed"):
        story.extend(_programs_section(deal, styles, detail))
        if deal.get("programs"):
            story.append(Spacer(1, 14))
        story.extend(_pricing_section(deal, styles, detail))
        story.append(Spacer(1, 14))

    if detail == "detailed":
        terms = _terms_section(deal, styles, detail)
        if terms:
            story.extend(terms)
            story.append(Spacer(1, 14))

    story.extend(_disclosure_block(deal, styles))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "<i>For questions about this quote please contact your INEOS Grenadier retailer.</i>",
        styles["body_small"],
    ))

    doc.build(story, onFirstPage=_on_page_footer, onLaterPages=_on_page_footer)
    buf.seek(0)
    return buf.read()
