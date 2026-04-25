"""
Program bulletin PDF generator — matches INEOS Automotive Americas format.

Replicates the established bulletin style:
- Dark green title bar with program name + subtitle
- REGION / FOR ATTENTION / CONTACT metadata
- Program Overview in accent-bordered box
- Three key stat callout boxes
- Green-header sections: Stackability, Eligibility, Administration & Rules
- Quick Reference table
- Customer-facing advertising disclosures
- INEOS GRENADIER footer
"""

import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, ListFlowable, ListItem,
)
from sqlalchemy.orm import Session
from app.models.program import Program
from app.models.campaign_code import CampaignCode, CampaignCodeLayer
from app.config import settings

# ── INEOS brand colors ──
DARK_GREEN = colors.HexColor("#2D5A27")
LIGHT_GREEN = colors.HexColor("#3A7233")
GREEN_ACCENT = colors.HexColor("#4A8C42")
ONYX = colors.HexColor("#1D1D1D")
CHARCOAL = colors.HexColor("#171717")
MUSHROOM = colors.HexColor("#D9D7D0")
MUSHROOM_LIGHT = colors.HexColor("#FAFAF9")
DOVE = colors.HexColor("#E9E8E5")
IRON_SMOKE = colors.HexColor("#606060")
SILVER_DUST = colors.HexColor("#9F9F9F")
WHITE = colors.white

# ── Stacking knowledge per program type ──
STACKING_INFO = {
    "customer_cash": {
        "stackable_with": [
            "Loyalty programs",
            "Friends & Family programs",
            "Santander Standard Lease and Finance",
            "Built for Purpose Conquest programs",
        ],
        "not_stackable_with": [
            "Lease subvention programs",
            "APR / finance subvention programs",
            "CVP",
        ],
        "important_note": "Customer must choose either customer cash or lease/APR subvention where applicable.",
        "deal_types": "Applied at point of sale",
        "deal_flexibility": (
            "Consumer Cash can be used to lower the customer's monthly payment, including buying down "
            "the APR, reducing the amount financed, or discounting the vehicle price. This gives dealers "
            "flexibility to structure the deal in the way that best helps close the sale. Any rate buy-down "
            "must be clearly explained to the customer and shown in the final paperwork."
        ),
    },
    "bonus_cash": {
        "stackable_with": [
            "All national and regional incentive programs",
            "Customer Cash, APR Cash, Lease Cash",
            "Loyalty and Conquest programs",
        ],
        "not_stackable_with": [],
        "important_note": "Bonus Cash is additive and applies to all deal types.",
        "deal_types": "All deal types (Cash, APR, Lease)",
    },
    "apr_cash": {
        "stackable_with": [
            "Loyalty programs",
            "Conquest programs",
            "Bonus Cash",
            "Santander subvented APR programs",
        ],
        "not_stackable_with": [
            "Customer Cash",
            "Lease subvention programs",
            "CVP",
        ],
        "important_note": "APR Cash is only available through Santander-financed transactions.",
        "deal_types": "APR / Retail Finance only",
    },
    "lease_cash": {
        "stackable_with": [
            "Loyalty programs",
            "Conquest programs",
            "Bonus Cash",
            "Santander subvented Lease programs",
        ],
        "not_stackable_with": [
            "Customer Cash",
            "APR subvention programs",
            "CVP",
        ],
        "important_note": "Lease Cash is only available on Santander-contracted lease transactions.",
        "deal_types": "Lease only",
    },
    "loyalty": {
        "stackable_with": [
            "All national and regional incentive programs",
            "Customer Cash, APR Cash, Lease Cash",
            "Conquest programs",
            "Friends & Family / Business Partner programs",
            "Arcane Works Dealer Cash",
            "Dealer Employee Lease Cash",
            "Costco program",
        ],
        "not_stackable_with": [],
        "important_note": "Loyalty Rebate is fully stackable with all programs.",
        "deal_types": "All deal types (Lease, Retail Finance, Cash)",
        "eligibility_requirements": [
            "Customer must be a current registered owner or lessee of an INEOS Grenadier (any model year)",
            "Ownership or lease must be verified through standard proof of ownership documentation and retained in deal jacket",
        ],
        "acceptable_documentation": [
            "Current vehicle registration showing the customer as owner/lessee",
            "Current insurance card/insurance policy showing the customer and the VIN",
        ],
    },
    "conquest": {
        "stackable_with": [
            "National customer cash programs",
            "Santander subvented APR programs",
            "Loyalty programs",
        ],
        "not_stackable_with": [
            "CVP",
        ],
        "important_note": "Conquest eligibility requires proof of ownership/lease of qualifying competitive vehicle.",
        "deal_types": "Retail Finance, Lease, and Cash",
        "conquest_brands": [
            "Jeep Gladiator",
            "Toyota Tacoma / Tundra",
            "Ford Ranger / F-150",
            "Chevrolet Colorado / Silverado",
            "GMC Canyon / Sierra",
            "RAM 1500",
            "Tesla Cybertruck",
            "Rivian R1T",
        ],
    },
    "cvp": {
        "stackable_with": [
            "Santander subvented CPO/CBI rates (at CVP retirement)",
        ],
        "not_stackable_with": [
            "New car incentive programs",
            "Customer Cash",
            "APR / Lease subvention programs",
            "Conquest programs",
        ],
        "important_note": "CVP units are not eligible for new car incentives but are eligible for Santander subvented CPO/CBI rates.",
        "deal_types": "CVP enrollment",
    },
    "demonstrator": {
        "stackable_with": [
            "Bonus Cash (where applicable)",
        ],
        "not_stackable_with": [
            "Customer Cash",
            "APR / Lease subvention programs",
            "Conquest programs",
            "CVP",
        ],
        "important_note": "Demonstrator program has separate eligibility and documentation requirements.",
        "deal_types": "Demonstrator use",
    },
    "tactical": {
        "stackable_with": [
            "Per program-specific guidelines",
        ],
        "not_stackable_with": [
            "Per program-specific guidelines",
        ],
        "important_note": "Tactical programs may have unique stacking rules. Consult your RBM for details.",
        "deal_types": "Per program guidelines",
    },
}


def _spaced(text):
    """Convert text to S P A C E D  O U T format like the bulletins use.
    Each character gets a space, words get triple space between them.
    E.g., 'Program Overview' -> 'P R O G R A M   O V E R V I E W'
    """
    words = text.upper().split()
    spaced_words = [" ".join(word) for word in words]
    return "   ".join(spaced_words)


def _build_styles():
    """Build all paragraph styles matching the INEOS bulletin format."""
    s = {}

    s["title"] = ParagraphStyle(
        "title", fontSize=22, fontName="Helvetica-Bold", textColor=WHITE,
        leading=28, spaceAfter=2,
    )
    s["subtitle"] = ParagraphStyle(
        "subtitle", fontSize=11, fontName="Helvetica", textColor=colors.HexColor("#C0C0C0"),
        leading=14, spaceAfter=0,
    )
    s["meta_label"] = ParagraphStyle(
        "meta_label", fontSize=9, fontName="Helvetica-Bold", textColor=DARK_GREEN,
        leading=14, spaceBefore=2, spaceAfter=2,
    )
    s["meta_value"] = ParagraphStyle(
        "meta_value", fontSize=9, fontName="Helvetica", textColor=ONYX,
        leading=14, spaceBefore=2, spaceAfter=2,
    )
    s["overview_heading"] = ParagraphStyle(
        "overview_heading", fontSize=10, fontName="Helvetica-Bold", textColor=DARK_GREEN,
        leading=14, spaceBefore=0, spaceAfter=4,
    )
    s["overview_body"] = ParagraphStyle(
        "overview_body", fontSize=10, fontName="Helvetica", textColor=ONYX,
        leading=14, spaceAfter=4, alignment=TA_JUSTIFY,
    )
    s["section_heading"] = ParagraphStyle(
        "section_heading", fontSize=12, fontName="Helvetica-Bold", textColor=WHITE,
        leading=16, spaceBefore=0, spaceAfter=0,
    )
    s["subsection_heading"] = ParagraphStyle(
        "subsection_heading", fontSize=9, fontName="Helvetica-Bold", textColor=DARK_GREEN,
        leading=14, spaceBefore=8, spaceAfter=4,
    )
    s["body"] = ParagraphStyle(
        "body", fontSize=10, fontName="Helvetica", textColor=ONYX,
        leading=14, spaceAfter=4, alignment=TA_JUSTIFY,
    )
    s["body_bold"] = ParagraphStyle(
        "body_bold", fontSize=10, fontName="Helvetica-Bold", textColor=ONYX,
        leading=14, spaceAfter=4,
    )
    s["bullet"] = ParagraphStyle(
        "bullet", fontSize=10, fontName="Helvetica", textColor=ONYX,
        leading=14, spaceAfter=2, leftIndent=18, bulletIndent=6,
    )
    s["sub_bullet"] = ParagraphStyle(
        "sub_bullet", fontSize=9, fontName="Helvetica", textColor=IRON_SMOKE,
        leading=13, spaceAfter=2, leftIndent=36, bulletIndent=24,
    )
    s["important_label"] = ParagraphStyle(
        "important_label", fontSize=9, fontName="Helvetica-Bold", textColor=colors.HexColor("#CC3300"),
        leading=12, spaceBefore=4, spaceAfter=2,
    )
    s["important_body"] = ParagraphStyle(
        "important_body", fontSize=10, fontName="Helvetica-Bold", textColor=ONYX,
        leading=14, spaceAfter=4,
    )
    s["stat_label"] = ParagraphStyle(
        "stat_label", fontSize=7, fontName="Helvetica-Bold", textColor=DARK_GREEN,
        leading=10, alignment=TA_CENTER,
    )
    s["stat_value"] = ParagraphStyle(
        "stat_value", fontSize=22, fontName="Helvetica-Bold", textColor=ONYX,
        leading=26, alignment=TA_CENTER,
    )
    s["stat_sub"] = ParagraphStyle(
        "stat_sub", fontSize=8, fontName="Helvetica", textColor=IRON_SMOKE,
        leading=10, alignment=TA_CENTER,
    )
    s["qr_label"] = ParagraphStyle(
        "qr_label", fontSize=10, fontName="Helvetica-Bold", textColor=ONYX,
        leading=14,
    )
    s["qr_value"] = ParagraphStyle(
        "qr_value", fontSize=10, fontName="Helvetica", textColor=ONYX,
        leading=14,
    )
    s["disclaimer"] = ParagraphStyle(
        "disclaimer", fontSize=8, fontName="Helvetica-Oblique", textColor=IRON_SMOKE,
        leading=11, spaceAfter=4, alignment=TA_JUSTIFY,
    )
    s["disclaimer_heading"] = ParagraphStyle(
        "disclaimer_heading", fontSize=9, fontName="Helvetica-Bold", textColor=DARK_GREEN,
        leading=12, spaceBefore=8, spaceAfter=4,
    )
    s["footer"] = ParagraphStyle(
        "footer", fontSize=8, fontName="Helvetica-Oblique", textColor=SILVER_DUST,
        alignment=TA_CENTER, leading=10,
    )
    s["footer_brand"] = ParagraphStyle(
        "footer_brand", fontSize=10, fontName="Helvetica-Bold", textColor=ONYX,
        alignment=TA_CENTER, leading=14, spaceBefore=6,
    )
    s["contact_note"] = ParagraphStyle(
        "contact_note", fontSize=9, fontName="Helvetica-Oblique", textColor=IRON_SMOKE,
        leading=12, spaceBefore=8, spaceAfter=4,
    )
    return s


def _section_header(text, styles):
    """Create a green-background section header like the bulletins."""
    t = Table(
        [[Paragraph(text, styles["section_heading"])]],
        colWidths=[6.85 * inch],
        rowHeights=[0.35 * inch],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK_GREEN),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _title_bar(title, subtitle, styles):
    """Create the dark green title bar at top of page 1."""
    content = [
        [Paragraph(title, styles["title"])],
        [Paragraph(subtitle, styles["subtitle"])],
    ]
    t = Table(content, colWidths=[6.85 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK_GREEN),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (0, 0), 14),
        ("BOTTOMPADDING", (-1, -1), (-1, -1), 12),
    ]))
    return t


def _meta_row(label, value, styles):
    """REGION / FOR ATTENTION / CONTACT metadata rows."""
    t = Table(
        [[Paragraph(_spaced(label), styles["meta_label"]),
          Paragraph(value, styles["meta_value"])]],
        colWidths=[1.7 * inch, 5.15 * inch],
    )
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _overview_box(heading_text, body_text, styles):
    """Program overview in a box with green left accent border."""
    content = [
        Paragraph(_spaced(heading_text), styles["overview_heading"]),
        Paragraph(body_text, styles["overview_body"]),
    ]
    inner = Table([[content]], colWidths=[6.5 * inch])
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, DOVE),
        ("LINEBEFORE", (0, 0), (0, -1), 3, DARK_GREEN),
        ("BOX", (0, 0), (-1, -1), 0.5, DOVE),
    ]))
    return inner


def _stat_boxes(stats, styles):
    """Three stat callout boxes: [(label, value, sub), ...]"""
    cells = []
    for label, value, sub in stats:
        cell_content = [
            Paragraph(_spaced(label), styles["stat_label"]),
            Spacer(1, 2),
            Paragraph(value, styles["stat_value"]),
            Paragraph(sub, styles["stat_sub"]),
        ]
        cells.append(cell_content)

    t = Table([cells], colWidths=[2.28 * inch] * 3)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, DOVE),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, DOVE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def _important_box(text, styles):
    """Red-labeled IMPORTANT callout box."""
    content = [
        [Paragraph(_spaced("Important"), styles["important_label"])],
        [Paragraph(f"<b>{text}</b>", styles["important_body"])],
    ]
    t = Table(content, colWidths=[6.5 * inch])
    t.setStyle(TableStyle([
        ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor("#CC3300")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (0, 0), 4),
        ("BOTTOMPADDING", (-1, -1), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF8F6")),
    ]))
    return t


def _quick_reference_table(rows, styles):
    """Quick Reference key-value table."""
    data = []
    for label, value in rows:
        data.append([
            Paragraph(f"<b>{label}</b>", styles["qr_label"]),
            Paragraph(value, styles["qr_value"]),
        ])
    t = Table(data, colWidths=[2.0 * inch, 4.85 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, DOVE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, DOVE),
    ]))
    return t


def _footer_block(page_num, styles):
    """Footer with INEOS|GRENADIER branding."""
    elements = [
        Spacer(1, 20),
        HRFlowable(width="100%", thickness=0.5, color=MUSHROOM, spaceAfter=6),
        Paragraph("IN<b>EO</b>S | G R E N <font color='#FF4639'>A</font> D I E R", styles["footer_brand"]),
        Paragraph(f"Confidential &middot; INEOS Automotive Americas &middot; Page {page_num}", styles["footer"]),
    ]
    return elements


def _get_eligible_models_text(program):
    """Extract eligible models description from program rules."""
    body_styles = []
    model_years = []
    for rule in program.rules:
        if rule.rule_type == "body_style":
            val = rule.value if isinstance(rule.value, list) else [rule.value]
            body_styles = [str(v).replace("_", " ").title() for v in val]
        elif rule.rule_type == "model_year":
            val = rule.value if isinstance(rule.value, list) else [rule.value]
            model_years = [str(v) for v in val]

    parts = []
    if model_years:
        years = " & ".join(model_years)
    else:
        years = "All model years"
    if body_styles:
        bodies = " & ".join(body_styles)
    else:
        bodies = "Station Wagon & Quartermaster"
    return f"{years} INEOS Grenadier {bodies}"


def _get_stacking_info(program_type):
    """Get stacking info for a program type, with fallback."""
    return STACKING_INFO.get(program_type, STACKING_INFO.get("tactical", {}))


def generate_program_bulletin(db: Session, program_id: str) -> str:
    """Generate a PDF program bulletin matching INEOS format. Returns file path."""
    program = db.query(Program).filter(Program.id == program_id).first()
    if not program:
        raise ValueError("Program not found")

    styles = _build_styles()
    os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

    safe_name = program.name.replace(" ", "_").replace("/", "-")[:50]
    filename = f"Bulletin_{safe_name}_{datetime.now().strftime('%Y%m%d')}.pdf"
    filepath = os.path.join(settings.OUTPUT_DIR, filename)

    doc = SimpleDocTemplate(
        filepath, pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
    )

    story = []
    type_label = program.program_type.replace("_", " ").upper()
    month_year = program.effective_date.strftime("%B %Y")
    eff = program.effective_date.strftime("%B %d, %Y") if program.effective_date else ""
    exp = program.expiration_date.strftime("%B %d, %Y") if program.expiration_date else ""
    eff_short = program.effective_date.strftime("%B %d") if program.effective_date else ""
    exp_short = program.expiration_date.strftime("%B %d, %Y") if program.expiration_date else ""
    amount = float(program.per_unit_amount or 0)
    amount_str = f"${amount:,.0f}"
    eligible_models = _get_eligible_models_text(program)
    stacking = _get_stacking_info(program.program_type)

    # ═══════════════════ PAGE 1 ═══════════════════

    # Title bar
    story.append(_title_bar(
        program.name.upper(),
        f"Program Bulletin | {month_year}",
        styles
    ))
    story.append(Spacer(1, 14))

    # Metadata
    story.append(_meta_row("Region", "United States of America", styles))
    story.append(_meta_row("For Attention", "Dealer Principal, General Manager, Sales &amp; F&amp;I Managers", styles))
    story.append(_meta_row("Contact", "Regional Business Managers (RBM)", styles))
    story.append(Spacer(1, 12))

    # Program Overview box
    overview_text = program.description or (
        f"This program provides incentive support for eligible INEOS Grenadier vehicles "
        f"from {eff} through {exp}."
    )
    story.append(_overview_box("Program Overview", overview_text, styles))
    story.append(Spacer(1, 14))

    # Stat callout boxes — context-dependent
    if program.program_type == "customer_cash":
        stats = [
            ("Station Wagon", amount_str, "customer cash"),
            ("Quartermaster", amount_str, "customer cash"),
            ("Incl. Arcane Works", "Yes", "all SW trims eligible"),
        ]
    elif program.program_type == "loyalty":
        stats = [
            ("Rebate", amount_str, "per transaction"),
            ("Deal Types", "All", "lease, finance, cash"),
            ("Stacking", "Full", "with all programs"),
        ]
    elif program.program_type == "conquest":
        stats = [
            ("Customer Cash", amount_str, "applied at point of sale"),
            ("Deal Types", "All", "finance, lease, cash"),
            ("Conquest Req", "Yes", "qualifying trade brand"),
        ]
    elif program.program_type == "cvp":
        stats = [
            ("Total Incentive", amount_str, "per enrolled VIN"),
            ("In-Service", "90 Days", "minimum requirement"),
            ("Mileage Min", "5,000", "minimum at out of service"),
        ]
    else:
        stats = [
            ("Incentive", amount_str, "per vehicle"),
            ("Effective Period", f"{eff_short} \u2013 {exp_short}", ""),
            ("Eligible Models", "All Grenadier", eligible_models.split("Grenadier")[-1].strip() if "Grenadier" in eligible_models else ""),
        ]
    story.append(_stat_boxes(stats, styles))
    story.append(Spacer(1, 16))

    # ── Amount by model section (for cash-type programs) ──
    if program.program_type in ("customer_cash", "bonus_cash"):
        story.append(_section_header(f"{type_label} BY MODEL", styles))
        story.append(Spacer(1, 6))
        model_data = [
            [Paragraph("<b>Model</b>", styles["body_bold"]),
             Paragraph(f"<b>{type_label.title()}</b>", styles["body_bold"])],
        ]
        for rule in program.rules:
            if rule.rule_type == "body_style":
                vals = rule.value if isinstance(rule.value, list) else [rule.value]
                for bs in vals:
                    for yr_rule in program.rules:
                        if yr_rule.rule_type == "model_year":
                            yrs = yr_rule.value if isinstance(yr_rule.value, list) else [yr_rule.value]
                            for yr in yrs:
                                label = f"{yr.replace('MY', '20')} Grenadier {bs.replace('_', ' ').title()}"
                                model_data.append([
                                    Paragraph(f"<b>{label}</b>", styles["body"]),
                                    Paragraph(amount_str, styles["body"]),
                                ])
                            break
                break
        if len(model_data) > 1:
            mt = Table(model_data, colWidths=[4.35 * inch, 2.5 * inch])
            mt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DOVE),
                ("LINEBELOW", (0, 0), (-1, -2), 0.5, DOVE),
                ("LINEBELOW", (0, -1), (-1, -1), 0.5, DOVE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]))
            story.append(mt)
        story.append(Spacer(1, 14))

    # ── Stackability & Compatibility ──
    story.append(_section_header("STACKABILITY & COMPATIBILITY", styles))
    story.append(Spacer(1, 8))

    if stacking.get("stackable_with"):
        story.append(Paragraph(_spaced("Eligible for Stacking With"), styles["subsection_heading"]))
        for item in stacking["stackable_with"]:
            story.append(Paragraph(f"&bull; {item}", styles["bullet"]))

    if stacking.get("not_stackable_with"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(_spaced("Not Stackable With"), styles["subsection_heading"]))
        for item in stacking["not_stackable_with"]:
            story.append(Paragraph(f"&bull; {item}", styles["bullet"]))

    if stacking.get("important_note"):
        story.append(Spacer(1, 6))
        story.append(_important_box(stacking["important_note"], styles))
    story.append(Spacer(1, 14))

    # ── Eligibility Requirements (for loyalty/conquest) ──
    if program.program_type == "loyalty" and stacking.get("eligibility_requirements"):
        story.append(_section_header("ELIGIBILITY REQUIREMENTS", styles))
        story.append(Spacer(1, 8))
        for req in stacking["eligibility_requirements"]:
            story.append(Paragraph(f"&bull; {req}", styles["bullet"]))
        if stacking.get("acceptable_documentation"):
            story.append(Spacer(1, 4))
            story.append(Paragraph(_spaced("Acceptable Documentation"), styles["subsection_heading"]))
            for doc_item in stacking["acceptable_documentation"]:
                story.append(Paragraph(f"&#9702; {doc_item}", styles["sub_bullet"]))
        story.append(Spacer(1, 14))

    if program.program_type == "conquest" and stacking.get("conquest_brands"):
        story.append(_section_header("CONQUEST ELIGIBILITY", styles))
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            "Customer must currently own or lease a 2018 model year or newer vehicle from the following:",
            styles["body"]
        ))
        for brand in stacking["conquest_brands"]:
            story.append(Paragraph(f"&bull; {brand}", styles["bullet"]))
        story.append(Spacer(1, 4))
        story.append(Paragraph("&bull; Ownership or lease may be within the same household (same garaging address)", styles["bullet"]))
        story.append(Paragraph("&bull; <b>Trade-in</b> is not required", styles["bullet"]))
        story.append(Spacer(1, 14))

    # ── Dealer Flexibility (for customer cash) ──
    if stacking.get("deal_flexibility"):
        story.append(_section_header("DEALER FLEXIBILITY", styles))
        story.append(Spacer(1, 8))
        story.append(Paragraph(stacking["deal_flexibility"], styles["body"]))
        story.append(Spacer(1, 14))

    # ══════════════ PAGE 2 content ══════════════

    # ── Administration & Rules ──
    story.append(_section_header("ADMINISTRATION & RULES", styles))
    story.append(Spacer(1, 8))
    admin_rules = [
        "Retailer must verify customer eligibility prior to applying incentive",
        "Retain all required documentation in the deal jacket for audit and compliance purposes",
        "Apply incentives in accordance with program rules and reporting requirements",
        "Incentive must be claimed at the time of retail delivery",
    ]
    for rule_text in admin_rules:
        story.append(Paragraph(f"&bull; {rule_text}", styles["bullet"]))
    story.append(Spacer(1, 6))

    story.append(Paragraph(_spaced("Program Notes"), styles["subsection_heading"]))
    program_notes = [
        "Incentive may not be redeemed for cash",
        "Offer is non-transferable",
        "Cannot be combined with programs where prohibited by law",
        "Program subject to modification or termination at any time without notice",
        "INEOS Automotive Americas, LLC reserves the right to audit all incentive claims",
        "Falsification of eligibility documentation may result in chargeback and program disqualification",
    ]
    for note in program_notes:
        story.append(Paragraph(f"&#9702; {note}", styles["sub_bullet"]))
    story.append(Spacer(1, 14))

    # ── Additional Notes ──
    story.append(_section_header("ADDITIONAL NOTES", styles))
    story.append(Spacer(1, 8))
    additional = [
        f"<b>New vehicles only:</b> Offers apply only to new, untitled {eligible_models.split(' INEOS')[0] if ' INEOS' in eligible_models else ''} model year vehicles",
        "Standard eligibility rules, documentation requirements, and program audits apply",
        "No substitution, transfer, or retroactive application unless explicitly approved",
        "All incentive claims are subject to verification and audit by INEOS Automotive Americas, LLC",
        "Dealer is responsible for ensuring all documentation is complete and accurate at time of sale",
        "Program subject to change or termination at any time",
    ]
    for item in additional:
        story.append(Paragraph(f"&bull; {item}", styles["bullet"]))
    story.append(Spacer(1, 14))

    # ── Quick Reference ──
    story.append(_section_header("QUICK REFERENCE", styles))
    story.append(Spacer(1, 8))

    deal_types = stacking.get("deal_types", "Applied at point of sale")
    stackable_str = ", ".join(stacking.get("stackable_with", [])[:3]) if stacking.get("stackable_with") else "N/A"
    not_stackable_str = ", ".join(stacking.get("not_stackable_with", [])[:3]) if stacking.get("not_stackable_with") else "N/A"

    qr_rows = [
        ("Program", program.name),
        ("Effective Period", f"{eff_short} \u2013 {exp_short}"),
        ("Eligible Models", eligible_models),
        (type_label.title(), f"{amount_str} per vehicle"),
        ("Deal Types", deal_types),
        ("Stackable With", stackable_str),
        ("Not Stackable", not_stackable_str),
    ]
    if stacking.get("important_note"):
        qr_rows.append(("Key Rule", stacking["important_note"]))

    story.append(_quick_reference_table(qr_rows, styles))
    story.append(Spacer(1, 16))

    # ── Customer-Facing Advertising Disclosures ──
    # Gated on program.public_facing. Internal-only programs (e.g.
    # dealer employee, friends & family) skip this entire block —
    # the customer disclaimer text exists for advertising-compliance
    # reasons and doesn't apply when the doc never reaches a retail
    # customer. The "contact your RBM" sign-off stays either way
    # because that's relevant to internal readers too.
    public_facing = bool(getattr(program, "public_facing", True))
    if public_facing:
        story.append(Paragraph(_spaced("Cash Offer Disclosures"), styles["disclaimer_heading"]))
        story.append(Spacer(1, 4))

        # Generate per-model disclosures
        body_styles_for_disclosure = ["Station Wagon", "Quartermaster"]
        for rule in program.rules:
            if rule.rule_type == "body_style":
                vals = rule.value if isinstance(rule.value, list) else [rule.value]
                body_styles_for_disclosure = [str(v).replace("_", " ").title() for v in vals]
                break

        model_years_for_disclosure = []
        for rule in program.rules:
            if rule.rule_type == "model_year":
                vals = rule.value if isinstance(rule.value, list) else [rule.value]
                model_years_for_disclosure = [str(v).replace("MY", "20") for v in vals]
                break

        if not model_years_for_disclosure:
            model_years_for_disclosure = ["2025"]

        for my in model_years_for_disclosure:
            for bs in body_styles_for_disclosure:
                disclosure = (
                    f"<b>{amount_str} {type_label.title()} (National) \u2014 {my} INEOS Grenadier {bs}:</b> "
                    f"Available on new models purchased {eff_short} through {exp_short}. "
                    f"{type_label.title()} must be applied toward the final transaction price. "
                )
                if program.program_type == "customer_cash":
                    disclosure += "Not available with special APR or Retail Finance offers. "
                disclosure += (
                    "Not redeemable for cash. May not be combined with other incompatible offers. "
                    "Customer must take delivery and sign all required documents during the program period. "
                    "Additional taxes, fees, and dealer-installed equipment may apply. "
                    "Offer valid on in-stock vehicles only and subject to change without notice. "
                    "Additional restrictions may apply. "
                    "INEOS Automotive Americas, LLC reserves the right to modify or terminate this "
                    "program at any time. See retailer for full details."
                )
                story.append(Paragraph(disclosure, styles["disclaimer"]))
                story.append(Spacer(1, 4))
    else:
        # Visible reminder so admins reviewing the doc know the
        # customer disclosures were intentionally suppressed.
        story.append(Paragraph(
            "<b>INTERNAL DOCUMENT \u2014</b> customer-facing advertising disclosures suppressed because this program is marked internal-only.",
            styles["disclaimer"],
        ))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "<i>For questions regarding eligibility or compliance, please contact your Regional Business Manager.</i>",
        styles["contact_note"],
    ))

    # Footer
    story.extend(_footer_block(1, styles))

    doc.build(story)
    return filepath


def generate_quick_reference_card(db: Session) -> str:
    """Generate a single-page campaign code quick reference card PDF."""
    styles = _build_styles()
    os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
    filename = f"CampaignCode_QuickRef_{datetime.now().strftime('%Y%m%d')}.pdf"
    filepath = os.path.join(settings.OUTPUT_DIR, filename)

    doc = SimpleDocTemplate(
        filepath, pagesize=letter,
        leftMargin=0.5 * inch, rightMargin=0.5 * inch,
        topMargin=0.5 * inch, bottomMargin=0.5 * inch,
    )

    story = []
    story.append(_title_bar("CAMPAIGN CODE QUICK REFERENCE", f"Generated {datetime.now().strftime('%B %d, %Y')}", styles))
    story.append(Spacer(1, 10))

    codes = db.query(CampaignCode).filter(CampaignCode.active == True).order_by(CampaignCode.code).all()
    if codes:
        header = [
            Paragraph("<b>CODE</b>", styles["body_bold"]),
            Paragraph("<b>MY</b>", styles["body_bold"]),
            Paragraph("<b>BODY</b>", styles["body_bold"]),
            Paragraph("<b>TYPE</b>", styles["body_bold"]),
            Paragraph("<b>LOY</b>", styles["body_bold"]),
            Paragraph("<b>CON</b>", styles["body_bold"]),
            Paragraph("<b>AMOUNT</b>", styles["body_bold"]),
        ]
        data = [header]
        for c in codes:
            data.append([
                Paragraph(f"<b>{c.code}</b>", styles["body"]),
                Paragraph(c.model_year or "", styles["body"]),
                Paragraph((c.body_style or "").replace("_", " ").title()[:8], styles["body"]),
                Paragraph((c.deal_type or "").upper(), styles["body"]),
                Paragraph("Y" if c.loyalty_flag else "", styles["body"]),
                Paragraph("Y" if c.conquest_flag else "", styles["body"]),
                Paragraph(f"${float(c.support_amount):,.0f}", styles["body"]),
            ])

        t = Table(data, colWidths=[0.95*inch, 0.55*inch, 0.95*inch, 0.65*inch, 0.45*inch, 0.45*inch, 0.95*inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK_GREEN),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, DOVE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, MUSHROOM_LIGHT]),
        ]))
        story.append(t)

    story.extend(_footer_block(1, styles))
    doc.build(story)
    return filepath
