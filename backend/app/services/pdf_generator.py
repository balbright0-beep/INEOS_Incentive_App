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
from app.models.program import Program, ProgramVin
from app.models.campaign_code import CampaignCode, CampaignCodeLayer
from app.config import settings

# ── INEOS brand colors — match the web app palette ──
# Onyx for primary structure (title bar, section headers); flare-red
# as accent for borders + the brand mark. Mushroom-light + dove for
# the soft neutral panels. Drops the dark-green-only palette the
# original bulletin used so the doc reads as part of the same brand
# system as /lookup/ and the SPA.
ONYX = colors.HexColor("#1D1D1D")
CHARCOAL = colors.HexColor("#171717")
FLARE_RED = colors.HexColor("#FF4639")
FLARE_RED_DEEP = colors.HexColor("#CC2200")
MUSHROOM = colors.HexColor("#D9D7D0")
MUSHROOM_LIGHT = colors.HexColor("#FAFAF9")
DOVE = colors.HexColor("#E9E8E5")
IRON_SMOKE = colors.HexColor("#606060")
SILVER_DUST = colors.HexColor("#9F9F9F")
SUCCESS_GREEN = colors.HexColor("#2C931E")
WHITE = colors.white

# Legacy alias kept so any unmodified call sites still work during
# the rebrand. Slated for removal after the full sweep.
DARK_GREEN = ONYX

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
    "dealer_cash": {
        "stackable_with": [
            "All national and regional incentive programs",
            "Customer Cash, APR Cash, Lease Cash, Bonus Cash",
            "Loyalty and Conquest programs",
            "Santander subvented APR / Lease programs",
        ],
        "not_stackable_with": [
            "CVP",
        ],
        "important_note": "Dealer Cash is dealer-funded and applied at retailer discretion. Stacks with all national retail programs by default.",
        "deal_types": "All retail deal types (Cash, APR, Lease)",
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
    "vin_specific": {
        "stackable_with": [
            "All national and regional retail programs",
            "Customer Cash, APR Cash, Lease Cash",
            "Dealer Cash",
            "Loyalty and Conquest programs",
            "Santander subvented APR / Lease",
        ],
        "not_stackable_with": [
            "CVP",
            "Demonstrator",
        ],
        "important_note": (
            "Eligibility is gated by VIN — only the units in the program's "
            "VIN list qualify. Per-VIN amounts vary; the calculator pulls "
            "the correct value when an eligible VIN is entered."
        ),
        "deal_types": "All deal types (Cash, APR, Lease)",
    },
}


def _spaced(text):
    """Compatibility shim: previous implementation manually injected
    spaces between every character to fake CSS letter-spacing
    (`P R O G R A M   O V E R V I E W`). That broke wrapping and
    rendered inconsistently — long words wrapped mid-letter, short
    words like "F O R" ran together.

    Now: the tracking comes from the ParagraphStyle itself via
    charSpace=. This function just returns the uppercased text so
    existing call sites keep working without each having to know
    about the styling change."""
    return text.upper()


def _build_styles():
    """Paragraph styles matching the INEOS web app brand: onyx structure
    + flare-red accents, Helvetica throughout (custom INEOS fonts can't
    be embedded server-side without bundled font files).

    All-caps headers use charSpace= for real letter-spacing instead of
    the previous manual `S P A C E D` text injection — wraps cleanly
    and renders consistently regardless of word length."""
    s = {}

    s["title"] = ParagraphStyle(
        "title", fontSize=22, fontName="Helvetica-Bold", textColor=WHITE,
        leading=26, spaceAfter=2, charSpace=0.6,
    )
    s["subtitle"] = ParagraphStyle(
        "subtitle", fontSize=10, fontName="Helvetica", textColor=colors.HexColor("#BFBFBF"),
        leading=13, spaceAfter=0, charSpace=1.2,
    )
    s["meta_label"] = ParagraphStyle(
        "meta_label", fontSize=8, fontName="Helvetica-Bold", textColor=IRON_SMOKE,
        leading=14, spaceBefore=2, spaceAfter=2, charSpace=1.4,
    )
    s["meta_value"] = ParagraphStyle(
        "meta_value", fontSize=10, fontName="Helvetica", textColor=ONYX,
        leading=14, spaceBefore=2, spaceAfter=2,
    )
    s["overview_heading"] = ParagraphStyle(
        "overview_heading", fontSize=9, fontName="Helvetica-Bold", textColor=ONYX,
        leading=14, spaceBefore=0, spaceAfter=6, charSpace=1.4,
    )
    s["overview_body"] = ParagraphStyle(
        "overview_body", fontSize=10.5, fontName="Helvetica", textColor=ONYX,
        leading=15, spaceAfter=4, alignment=TA_LEFT,
    )
    s["section_heading"] = ParagraphStyle(
        "section_heading", fontSize=11, fontName="Helvetica-Bold", textColor=WHITE,
        leading=14, spaceBefore=0, spaceAfter=0, charSpace=1.5,
    )
    s["subsection_heading"] = ParagraphStyle(
        "subsection_heading", fontSize=8.5, fontName="Helvetica-Bold", textColor=IRON_SMOKE,
        leading=14, spaceBefore=8, spaceAfter=4, charSpace=1.4,
    )
    s["body"] = ParagraphStyle(
        "body", fontSize=10, fontName="Helvetica", textColor=ONYX,
        leading=14, spaceAfter=4, alignment=TA_LEFT,
    )
    s["body_bold"] = ParagraphStyle(
        "body_bold", fontSize=10, fontName="Helvetica-Bold", textColor=ONYX,
        leading=14, spaceAfter=4,
    )
    s["bullet"] = ParagraphStyle(
        "bullet", fontSize=10, fontName="Helvetica", textColor=ONYX,
        leading=14, spaceAfter=3, leftIndent=18, bulletIndent=6,
    )
    s["sub_bullet"] = ParagraphStyle(
        "sub_bullet", fontSize=9, fontName="Helvetica", textColor=IRON_SMOKE,
        leading=13, spaceAfter=2, leftIndent=36, bulletIndent=24,
    )
    s["important_label"] = ParagraphStyle(
        "important_label", fontSize=8, fontName="Helvetica-Bold", textColor=FLARE_RED_DEEP,
        leading=12, spaceBefore=4, spaceAfter=2, charSpace=1.5,
    )
    s["important_body"] = ParagraphStyle(
        "important_body", fontSize=10, fontName="Helvetica-Bold", textColor=ONYX,
        leading=14, spaceAfter=4,
    )
    s["stat_label"] = ParagraphStyle(
        "stat_label", fontSize=7.5, fontName="Helvetica-Bold", textColor=IRON_SMOKE,
        leading=10, alignment=TA_CENTER, charSpace=1.2,
    )
    s["stat_value"] = ParagraphStyle(
        "stat_value", fontSize=20, fontName="Helvetica-Bold", textColor=ONYX,
        leading=24, alignment=TA_CENTER,
    )
    # Smaller variant for non-currency stat values (body labels, date
    # ranges, multi-word phrases) that wrap awkwardly inside the
    # narrow stat-box columns at the 20pt currency size.
    s["stat_value_text"] = ParagraphStyle(
        "stat_value_text", fontSize=12.5, fontName="Helvetica-Bold", textColor=ONYX,
        leading=15, alignment=TA_CENTER,
    )
    s["stat_sub"] = ParagraphStyle(
        "stat_sub", fontSize=8, fontName="Helvetica", textColor=IRON_SMOKE,
        leading=11, alignment=TA_CENTER,
    )
    s["qr_label"] = ParagraphStyle(
        "qr_label", fontSize=9.5, fontName="Helvetica-Bold", textColor=IRON_SMOKE,
        leading=14, charSpace=0.6,
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
        "disclaimer_heading", fontSize=8.5, fontName="Helvetica-Bold", textColor=IRON_SMOKE,
        leading=12, spaceBefore=8, spaceAfter=4, charSpace=1.4,
    )
    s["footer"] = ParagraphStyle(
        "footer", fontSize=7.5, fontName="Helvetica", textColor=SILVER_DUST,
        alignment=TA_CENTER, leading=10, charSpace=0.4,
    )
    s["footer_brand"] = ParagraphStyle(
        "footer_brand", fontSize=10, fontName="Helvetica-Bold", textColor=ONYX,
        alignment=TA_CENTER, leading=14, spaceBefore=6, charSpace=2.0,
    )
    s["contact_note"] = ParagraphStyle(
        "contact_note", fontSize=9, fontName="Helvetica-Oblique", textColor=IRON_SMOKE,
        leading=12, spaceBefore=8, spaceAfter=4,
    )
    return s


def _section_header(text, styles):
    """Onyx-background section header. Letter-spacing comes from the
    section_heading style's charSpace= rather than manual `_spaced()`
    injection so wrapping behaves correctly on long strings."""
    t = Table(
        [[Paragraph(text.upper(), styles["section_heading"])]],
        colWidths=[7.0 * inch],
        rowHeights=[0.32 * inch],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ONYX),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _title_bar(title, subtitle, styles):
    """Onyx title bar with a flare-red accent line beneath. Mirrors
    the `border-bottom: 3px solid flare-red` treatment on the public
    /lookup/ header so the bulletin reads as part of the same brand
    system."""
    content = [
        [Paragraph(title.upper(), styles["title"])],
        [Paragraph(subtitle.upper(), styles["subtitle"])],
    ]
    t = Table(content, colWidths=[7.0 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ONYX),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING", (0, 0), (0, 0), 16),
        ("BOTTOMPADDING", (-1, -1), (-1, -1), 14),
        ("LINEBELOW", (0, -1), (-1, -1), 3, FLARE_RED),
    ]))
    return t


def _meta_row(label, value, styles):
    """REGION / FOR ATTENTION / CONTACT metadata rows. Label uses the
    eyebrow tracking treatment; value reads as standard body text."""
    t = Table(
        [[Paragraph(label.upper(), styles["meta_label"]),
          Paragraph(value, styles["meta_value"])]],
        colWidths=[1.7 * inch, 5.3 * inch],
    )
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _overview_box(heading_text, body_text, styles):
    """Program overview in a card with a flare-red left accent — same
    visual treatment as the result-card border on the wizard."""
    content = [
        Paragraph(heading_text.upper(), styles["overview_heading"]),
        Paragraph(body_text, styles["overview_body"]),
    ]
    inner = Table([[content]], colWidths=[6.7 * inch])
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1, -1), MUSHROOM_LIGHT),
        ("LINEBEFORE", (0, 0), (0, -1), 3, FLARE_RED),
        ("BOX", (0, 0), (-1, -1), 0.5, DOVE),
    ]))
    return inner


def _stat_boxes(stats, styles):
    """Variable-width stat callout boxes. Accepts 1-4 entries; column
    widths split evenly across 7.0in. Onyx top accent line ties them
    to the section headers."""
    n = len(stats)
    if n == 0:
        return Spacer(1, 0)
    col_w = 7.0 / n
    # Pick stat_value (20pt bold currency) only for short numeric-looking
    # strings — anything longer than ~10 chars wraps in the narrow column,
    # so multi-word phrases like "Station Wagon + Quartermaster" or date
    # ranges like "Apr 01 – Apr 30, 2026" use the smaller stat_value_text
    # variant.
    def _value_style(v):
        s = str(v)
        if len(s) <= 10 and (s.startswith("$") or s.replace(",", "").replace(".", "").isdigit() or s in ("All", "Yes", "No")):
            return styles["stat_value"]
        return styles["stat_value_text"]

    cells = []
    for label, value, sub in stats:
        cell_content = [
            Paragraph(label.upper(), styles["stat_label"]),
            Spacer(1, 4),
            Paragraph(value, _value_style(value)),
            Paragraph(sub, styles["stat_sub"]) if sub else Spacer(1, 0),
        ]
        cells.append(cell_content)

    t = Table([cells], colWidths=[col_w * inch] * n)
    style_cmds = [
        ("BOX", (0, 0), (-1, -1), 0.5, DOVE),
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("LINEABOVE", (0, 0), (-1, 0), 2, ONYX),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]
    if n > 1:
        style_cmds.append(("LINEAFTER", (0, 0), (-2, -1), 0.5, DOVE))
    t.setStyle(TableStyle(style_cmds))
    return t


def _important_box(text, styles):
    """Flare-red-bordered IMPORTANT callout. Background is a soft
    red-tinted neutral so it reads as a warning without being loud."""
    content = [
        [Paragraph("Important".upper(), styles["important_label"])],
        [Paragraph(f"<b>{text}</b>", styles["important_body"])],
    ]
    t = Table(content, colWidths=[6.7 * inch])
    t.setStyle(TableStyle([
        ("LINEBEFORE", (0, 0), (0, -1), 3, FLARE_RED_DEEP),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (-1, -1), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF6F5")),
    ]))
    return t


def _quick_reference_table(rows, styles):
    """Quick Reference key-value table. Alternating row backgrounds
    so the eye can scan label→value pairs quickly."""
    data = []
    for label, value in rows:
        data.append([
            Paragraph(label.upper(), styles["qr_label"]),
            Paragraph(value, styles["qr_value"]),
        ])
    t = Table(data, colWidths=[1.85 * inch, 5.15 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, DOVE),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, MUSHROOM_LIGHT]),
    ]))
    return t


def _on_page_footer(canvas, doc):
    """Page-template callback: paints the footer + page-number stamp on
    every page so multi-page bulletins don't all say "Page 1". Uses
    canvas drawing directly (faster than re-flowing a Paragraph for
    each page)."""
    canvas.saveState()
    page_w, page_h = letter
    # Divider line above the footer
    canvas.setStrokeColor(MUSHROOM)
    canvas.setLineWidth(0.5)
    canvas.line(0.6 * inch, 0.55 * inch, page_w - 0.6 * inch, 0.55 * inch)
    # Brand mark — IN-EO-S | GRENADIER with red 'A'
    canvas.setFillColor(ONYX)
    canvas.setFont("Helvetica-Bold", 9.5)
    brand_text = "INEOS  |  GRENADIER"
    text_w = canvas.stringWidth(brand_text, "Helvetica-Bold", 9.5)
    x = (page_w - text_w) / 2
    canvas.drawString(x, 0.40 * inch, brand_text)
    # The 'A' in GRENADIER painted red over the existing one — find
    # its x position by string-width arithmetic.
    prefix = "INEOS  |  GREN"
    a_x = x + canvas.stringWidth(prefix, "Helvetica-Bold", 9.5)
    canvas.setFillColor(FLARE_RED)
    canvas.drawString(a_x, 0.40 * inch, "A")
    # Confidential + page number
    canvas.setFillColor(SILVER_DUST)
    canvas.setFont("Helvetica", 7.5)
    footer = f"Confidential  ·  INEOS Automotive Americas  ·  Page {doc.page}"
    fw = canvas.stringWidth(footer, "Helvetica", 7.5)
    canvas.drawString((page_w - fw) / 2, 0.27 * inch, footer)
    canvas.restoreState()


# Retained for backwards compatibility — older call sites that built
# the footer as flowables. The page-template callback above is the
# preferred path; this helper is now a no-op spacer.
def _footer_block(page_num, styles):
    return [Spacer(1, 0)]


def _rule_values(program, rule_type):
    """Pull the value list for a single rule_type off a program. Always
    returns a list (or [] when the rule isn't present), so callers can
    iterate without None-checks."""
    for rule in program.rules:
        if rule.rule_type == rule_type:
            v = rule.value
            return v if isinstance(v, list) else [v]
    return []


_SPECIAL_EDITION_LABELS = {
    "arcane_works_detour": "Arcane Works Detour",
    "iceland_tactical": "Iceland Tactical",
}


def _get_eligible_models_text(program):
    """Compose the 'eligible models' descriptor from the program's
    actual rules. Was previously model_year + body only — now also
    surfaces trim / state / special_edition restrictions so a deal
    targeted at e.g. "MY26 SW Trialmaster, CA only" actually says so."""
    model_years = [str(v) for v in _rule_values(program, "model_year")]
    body_styles = [str(v).replace("_", " ").title() for v in _rule_values(program, "body_style")]
    trims = [str(v) for v in _rule_values(program, "trim")]
    states = [str(v).upper() for v in _rule_values(program, "state")]
    specials = [_SPECIAL_EDITION_LABELS.get(str(v), str(v).replace("_", " ").title())
                for v in _rule_values(program, "special_edition")]

    years = " & ".join(model_years) if model_years else "All model years"
    bodies = " & ".join(body_styles) if body_styles else "Station Wagon & Quartermaster"
    base = f"{years} INEOS Grenadier {bodies}"

    suffix_parts = []
    if trims:
        suffix_parts.append(f"trim: {', '.join(trims)}")
    if specials:
        suffix_parts.append(f"edition: {', '.join(specials)}")
    if states:
        suffix_parts.append(f"states: {', '.join(states)}")
    if suffix_parts:
        return f"{base} ({'; '.join(suffix_parts)})"
    return base


def _format_program_summary(program) -> str:
    """One-line program descriptor for cross-references in stacking
    exclusions. Keeps the bulletin readable even when the user
    excluded a specific other program rather than a whole type."""
    type_label = (program.program_type or "").replace("_", " ").title()
    amount = float(program.per_unit_amount or 0)
    return f"{program.name} ({type_label}, ${amount:,.0f})" if amount else f"{program.name} ({type_label})"


def _resolve_excluded_programs(db: Session, program) -> list:
    """Look up the Program rows whose ids appear in this program's
    not_stackable_program_ids. Surfaces them in the bulletin's
    "Not stackable with" section so the doc reflects what the admin
    actually configured in the wizard, not just generic boilerplate."""
    ids = list(getattr(program, "not_stackable_program_ids", None) or [])
    if not ids:
        return []
    return db.query(Program).filter(Program.id.in_(ids)).all()


# Display labels for program types — keeps the matrix-derived list
# readable even when the underlying enum is snake_case. Tracked
# separately from STACKING_INFO descriptions because those are
# human-readable categories ("Friends & Family") that don't 1:1
# map to enum values.
_PROGRAM_TYPE_LABELS = {
    "customer_cash": "Customer Cash",
    "bonus_cash": "Bonus Cash",
    "apr_cash": "APR Cash",
    "lease_cash": "Lease Cash",
    "dealer_cash": "Dealer Cash",
    "vin_specific": "VIN-Specific Rebate",
    "loyalty": "Loyalty",
    "conquest": "Conquest",
    "tactical": "Tactical / Special",
    "cvp": "CVP",
    "demonstrator": "Demonstrator",
    "other": "Other",
}


def _live_stacking_compat(db: Session, program_type: str) -> tuple[list[str], list[str]]:
    """Compute the live (stackable_with, not_stackable_with) program
    types for a given program type by walking the StackingRule matrix
    in the DB, instead of relying on the static STACKING_INFO dict.

    Logic: this program_type can stack with another type when there
    exists at least one deal_type where BOTH are allowed. So we look
    up the deal types this program is allowed in, union the allowed-
    types lists for those deals, and that's the stackable set. The
    not-stackable set is everything else from the matrix.

    Returns ([stackable type labels], [not stackable type labels])
    sorted alphabetically. Used to surface a "Per current matrix"
    annotation alongside the boilerplate STACKING_INFO copy so the
    bulletin reflects admin-time changes to the matrix.
    """
    from app.services.stacking import get_stacking_matrix
    matrix = get_stacking_matrix(db)
    deal_types_for_self = [dt for dt, types in matrix.items() if program_type in types]
    if not deal_types_for_self:
        return [], []
    stackable_types: set[str] = set()
    for dt in deal_types_for_self:
        stackable_types.update(matrix.get(dt, []))
    stackable_types.discard(program_type)

    all_types: set[str] = set()
    for types in matrix.values():
        all_types.update(types)
    all_types.discard(program_type)
    not_stackable_types = all_types - stackable_types

    def label(t):
        return _PROGRAM_TYPE_LABELS.get(t, t.replace("_", " ").title())
    return (
        sorted(label(t) for t in stackable_types),
        sorted(label(t) for t in not_stackable_types),
    )


def _compute_important_note(program, stacking_info: dict, excluded_programs: list,
                            live_not_stack: list[str]) -> str:
    """Decide what the IMPORTANT callout should say. Three layers:

    1. Per-program exclusions (most authoritative — admin set them in
       the wizard for THIS program specifically).
    2. Live matrix mismatch — when the boilerplate claims "fully
       stackable" but the StackingRule matrix shows there ARE non-
       stackable types, the boilerplate is wrong; substitute the
       computed exclusions instead.
    3. Otherwise: use the boilerplate from STACKING_INFO."""
    if excluded_programs:
        names = ", ".join(p.name for p in excluded_programs)
        return (f"This program cannot be combined with: {names}. "
                "Standard type-level stacking rules also apply.")

    boilerplate = stacking_info.get("important_note", "")
    # Detect the "fully stackable" boilerplate that conflicts with a
    # non-empty matrix not-stack list. Word-fragment match keeps the
    # detection forgiving — the boilerplate text could be tweaked
    # without breaking this check.
    is_fully_stackable_claim = "fully stackable" in boilerplate.lower()
    if is_fully_stackable_claim and live_not_stack:
        return (f"Per the current stacking matrix, this program cannot be combined "
                f"with: {', '.join(live_not_stack)}. "
                "All other program types stack normally.")
    return boilerplate


def _get_stacking_info(program_type):
    """Get stacking info for a program type, with fallback. Used as
    BASELINE descriptive language; the bulletin also surfaces the
    program's actual not_stackable_program_ids on top of this."""
    return STACKING_INFO.get(program_type, STACKING_INFO.get("tactical", {}))


def _stats_for_program(program, vin_summary: dict | None = None):
    """Build the 3-up stat callouts from the program's actual rules.
    Previously these were hardcoded per type — a SW-only customer-cash
    program incorrectly showed both bodies at the same amount because
    body_style rules weren't consulted. Now the stats reflect what
    the program is actually targeting.

    vin_summary — optional aggregate from ProgramVin (count + amount
    range). Required for vin_specific programs because the per-unit
    amount on Program is meaningless for that type; the real numbers
    live in the per-VIN rows."""
    amount = float(program.per_unit_amount or 0)
    amount_str = f"${amount:,.0f}"
    type_label = (program.program_type or "").replace("_", " ").title()
    body_styles = _rule_values(program, "body_style")
    model_years = _rule_values(program, "model_year")
    eff = program.effective_date
    exp = program.expiration_date
    period_str = ""
    if eff and exp:
        period_str = f"{eff.strftime('%b %d')} – {exp.strftime('%b %d, %Y')}"

    pt = program.program_type
    if pt == "vin_specific":
        # Numbers come from the per-VIN list, not Program.per_unit_amount.
        # When the list is empty (program created but list not yet
        # uploaded) we still show the box so the bulletin layout is
        # consistent — just with "—" placeholders.
        s = vin_summary or {}
        count = int(s.get("count", 0) or 0)
        lo = float(s.get("min_amount", 0) or 0)
        hi = float(s.get("max_amount", 0) or 0)
        if count == 0:
            range_str = "—"
            range_sub = "no VINs uploaded yet"
        elif abs(lo - hi) < 0.01:
            range_str = f"${lo:,.0f}"
            range_sub = "uniform per VIN"
        else:
            range_str = f"${lo:,.0f} – ${hi:,.0f}"
            range_sub = "varies by VIN"
        return [
            ("Eligible VINs", f"{count:,}", "see VIN list"),
            ("Rebate Range", range_str, range_sub),
            ("Effective", period_str or "—", "current cycle"),
        ]

    if pt in ("customer_cash", "bonus_cash", "dealer_cash", "apr_cash", "lease_cash"):
        # Per-deal-type cash incentive — show amount + scope + period.
        body_label = (
            "All bodies" if not body_styles
            else " + ".join(b.replace("_", " ").title() for b in body_styles)
        )
        my_label = " + ".join(model_years) if model_years else "All MYs"
        return [
            (type_label, amount_str, "per vehicle"),
            ("Eligible Bodies", body_label, my_label),
            ("Effective", period_str or "—", "current cycle"),
        ]
    if pt == "loyalty":
        return [
            ("Loyalty Rebate", amount_str, "per transaction"),
            ("Deal Types", "All", "lease, finance, cash"),
            ("Stacking", "Standard", "see exclusions below"),
        ]
    if pt == "conquest":
        return [
            ("Conquest Cash", amount_str, "applied at point of sale"),
            ("Trade-in", "Not required", "qualifying brand only"),
            ("Deal Types", "All", "lease, finance, cash"),
        ]
    if pt == "cvp":
        return [
            ("Total Incentive", amount_str, "per enrolled VIN"),
            ("In-Service", "90 Days", "minimum requirement"),
            ("Mileage Min", "5,000 mi", "at out-of-service"),
        ]
    if pt == "demonstrator":
        return [
            ("Demo Cash", amount_str, "per demonstrator unit"),
            ("Deal Types", "Demo only", "separate eligibility"),
            ("Effective", period_str or "—", "current cycle"),
        ]
    # tactical / other — show two stats, omit the third filler box
    return [
        ("Incentive", amount_str, "per vehicle"),
        ("Effective", period_str or "—", "current cycle"),
    ]


def _amount_by_model_rows(program):
    """Generate the per-(model_year × body_style) rows for the
    AMOUNT BY MODEL table. Always emits the cross-product of the
    program's actual model_year × body_style rules — the previous
    nested-loop-with-break implementation only emitted rows for the
    first body_style rule, dropping data on multi-body programs."""
    amount = float(program.per_unit_amount or 0)
    amount_str = f"${amount:,.0f}"
    body_styles = _rule_values(program, "body_style") or ["station_wagon", "quartermaster"]
    model_years = _rule_values(program, "model_year") or ["MY25", "MY26"]
    trims = _rule_values(program, "trim")
    rows = []
    for my in model_years:
        for bs in body_styles:
            year = my.replace("MY", "20")
            label = f"{year} Grenadier {bs.replace('_', ' ').title()}"
            if trims:
                label += f" — {', '.join(trims)}"
            rows.append((label, amount_str))
    return rows


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
        topMargin=0.55 * inch, bottomMargin=0.75 * inch,
        title=f"INEOS Bulletin — {program.name}",
        author="INEOS Automotive Americas",
    )

    story = []
    type_label = program.program_type.replace("_", " ").upper()
    # Prefer the friendly display label (e.g. "VIN-Specific Rebate"
    # over "Vin Specific") when one's defined for the program type;
    # falls back to title-cased snake-case for any types that haven't
    # been added to _PROGRAM_TYPE_LABELS yet.
    type_title = _PROGRAM_TYPE_LABELS.get(program.program_type, type_label.title())
    month_year = program.effective_date.strftime("%B %Y") if program.effective_date else ""
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
    subtitle = f"Program Bulletin · {month_year}" if month_year else "Program Bulletin"
    story.append(_title_bar(program.name, subtitle, styles))
    story.append(Spacer(1, 16))

    # Resolve program-specific stacking exclusions for use later (the
    # admin can pick specific other programs to exclude in the wizard).
    excluded_programs = _resolve_excluded_programs(db, program)
    # Live compatibility from the StackingRule DB matrix — the bulletin
    # surfaces this alongside the boilerplate STACKING_INFO copy so
    # admin-time changes to the matrix actually flow through.
    live_stack, live_not_stack = _live_stacking_compat(db, program.program_type)
    public_facing = bool(getattr(program, "public_facing", True))

    # VIN-list aggregate for vin_specific programs. Loaded once here
    # so the stat box, the VIN coverage section, and the appendix all
    # share the same data without re-querying.
    vin_summary = None
    vin_rows = []
    if program.program_type == "vin_specific":
        vin_rows = (
            db.query(ProgramVin)
            .filter(ProgramVin.program_id == program.id)
            .order_by(ProgramVin.vin)
            .all()
        )
        amounts = [float(r.amount) for r in vin_rows]
        vin_summary = {
            "count": len(amounts),
            "min_amount": min(amounts) if amounts else 0.0,
            "max_amount": max(amounts) if amounts else 0.0,
            "total_amount": sum(amounts),
        }

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

    # Stat callouts — built from the program's actual rules so a
    # SW-only customer-cash program no longer shows both bodies at
    # the same amount, etc.
    story.append(_stat_boxes(_stats_for_program(program, vin_summary), styles))
    story.append(Spacer(1, 18))

    # VIN COVERAGE — per-VIN rebate breakdown for vin_specific programs.
    # Shows the count, total program value, and an inline VIN list when
    # the count is small enough to fit. Larger lists get a "see SPA"
    # pointer so the bulletin doesn't bloat to dozens of pages — the
    # full list is always queryable via the admin UI.
    if program.program_type == "vin_specific":
        story.append(_section_header("VIN Coverage", styles))
        story.append(Spacer(1, 8))
        if vin_summary and vin_summary.get("count"):
            count = vin_summary["count"]
            total = vin_summary.get("total_amount", 0)
            story.append(Paragraph(
                f"<b>{count:,}</b> VINs covered &middot; total program value "
                f"<b>${total:,.0f}</b>. Per-VIN amounts vary by unit; the "
                "calculator pulls the right rebate when an eligible VIN is entered.",
                styles["body"],
            ))
            # Inline list when small enough to be useful in the doc.
            # Threshold of 60 keeps even the densest list under a single
            # page worth of two-column rows; anything larger gets the
            # pointer instead.
            if count <= 60:
                story.append(Spacer(1, 8))
                story.append(Paragraph("Eligible VINs".upper(), styles["subsection_heading"]))
                # 2-column layout: VIN | amount, alternating rows for scan
                inline_rows = [[
                    Paragraph("<b>VIN</b>", styles["body_bold"]),
                    Paragraph("<b>Rebate</b>", styles["body_bold"]),
                ]]
                for r in vin_rows:
                    inline_rows.append([
                        Paragraph(r.vin, styles["body"]),
                        Paragraph(f"${float(r.amount):,.0f}", styles["body"]),
                    ])
                vt = Table(inline_rows, colWidths=[4.7 * inch, 2.3 * inch])
                vt.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), MUSHROOM_LIGHT),
                    ("LINEABOVE", (0, 0), (-1, 0), 1, ONYX),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, MUSHROOM),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.5, DOVE),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, MUSHROOM_LIGHT]),
                ]))
                story.append(vt)
            else:
                story.append(Spacer(1, 6))
                story.append(Paragraph(
                    f"<i>Full VIN list ({count:,} entries) available in the "
                    "admin Incentive Dashboard. The calculator validates each "
                    "VIN at deal entry and returns its specific rebate.</i>",
                    styles["body"],
                ))
        else:
            story.append(Paragraph(
                "<i>No VINs uploaded for this program yet. Upload the VIN "
                "list from the program edit screen to activate the rebate.</i>",
                styles["body"],
            ))
        story.append(Spacer(1, 16))

    # AMOUNT BY MODEL — every (model_year x body_style) the program targets,
    # built from the actual rules. Now applies to every cash-type program
    # (was only customer_cash + bonus_cash) and uses the rebuilt
    # _amount_by_model_rows helper that no longer drops rows when more
    # than one body_style rule is present.
    if program.program_type in ("customer_cash", "bonus_cash", "dealer_cash", "apr_cash", "lease_cash"):
        story.append(_section_header(f"{type_title} by Model", styles))
        story.append(Spacer(1, 8))
        model_rows = _amount_by_model_rows(program)
        if model_rows:
            data = [[
                Paragraph("<b>Model</b>", styles["body_bold"]),
                Paragraph(f"<b>{type_title}</b>", styles["body_bold"]),
            ]] + [
                [Paragraph(label, styles["body"]), Paragraph(val, styles["body"])]
                for label, val in model_rows
            ]
            mt = Table(data, colWidths=[4.7 * inch, 2.3 * inch])
            mt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), MUSHROOM_LIGHT),
                ("LINEABOVE", (0, 0), (-1, 0), 1, ONYX),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, MUSHROOM),
                ("LINEBELOW", (0, 1), (-1, -1), 0.5, DOVE),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, MUSHROOM_LIGHT]),
            ]))
            story.append(mt)
        story.append(Spacer(1, 16))

    # Stackability & Compatibility — three layers of detail:
    #   1. Boilerplate human-readable categories from STACKING_INFO
    #      ("Loyalty programs", "Friends & Family programs") for
    #      readability.
    #   2. Live stacking matrix verification — the program TYPES that
    #      currently allow this program per the StackingRule table.
    #      Reflects admin-time changes that diverge from boilerplate.
    #   3. Per-program exclusions from not_stackable_program_ids
    #      (most authoritative — overrides the others).
    # IMPORTANT note is computed: when explicit exclusions are set,
    # the boilerplate "fully stackable" claim becomes misleading, so
    # we replace it with the actual exclusion list.
    story.append(_section_header("Stackability & Compatibility", styles))
    story.append(Spacer(1, 8))

    if stacking.get("stackable_with"):
        story.append(Paragraph("Eligible for Stacking With".upper(), styles["subsection_heading"]))
        for item in stacking["stackable_with"]:
            story.append(Paragraph(f"&bull; {item}", styles["bullet"]))

    if live_stack:
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f"<i>Per current matrix:</i> {', '.join(live_stack)}",
            styles["body"],
        ))

    if excluded_programs:
        story.append(Spacer(1, 4))
        story.append(Paragraph("Specific Programs Excluded".upper(), styles["subsection_heading"]))
        for ep in excluded_programs:
            story.append(Paragraph(f"&bull; {_format_program_summary(ep)}", styles["bullet"]))

    if stacking.get("not_stackable_with"):
        story.append(Spacer(1, 4))
        story.append(Paragraph("Generally Not Stackable With".upper(), styles["subsection_heading"]))
        for item in stacking["not_stackable_with"]:
            story.append(Paragraph(f"&bull; {item}", styles["bullet"]))

    if live_not_stack:
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f"<i>Per current matrix:</i> {', '.join(live_not_stack)}",
            styles["body"],
        ))

    important_text = _compute_important_note(program, stacking, excluded_programs, live_not_stack)
    if important_text:
        story.append(Spacer(1, 8))
        story.append(_important_box(important_text, styles))
    story.append(Spacer(1, 14))

    # ── Eligibility Requirements (for loyalty/conquest) ──
    if program.program_type == "loyalty" and stacking.get("eligibility_requirements"):
        story.append(_section_header("Eligibility Requirements", styles))
        story.append(Spacer(1, 8))
        for req in stacking["eligibility_requirements"]:
            story.append(Paragraph(f"&bull; {req}", styles["bullet"]))
        if stacking.get("acceptable_documentation"):
            story.append(Spacer(1, 4))
            story.append(Paragraph("Acceptable Documentation".upper(), styles["subsection_heading"]))
            for doc_item in stacking["acceptable_documentation"]:
                story.append(Paragraph(f"&#9702; {doc_item}", styles["sub_bullet"]))
        story.append(Spacer(1, 14))

    if program.program_type == "conquest" and stacking.get("conquest_brands"):
        story.append(_section_header("Conquest Eligibility", styles))
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
        story.append(_section_header("Dealer Flexibility", styles))
        story.append(Spacer(1, 8))
        story.append(Paragraph(stacking["deal_flexibility"], styles["body"]))
        story.append(Spacer(1, 14))

    # ══════════════ PAGE 2 content ══════════════

    # ── Administration & Rules ──
    story.append(_section_header("Administration & Rules", styles))
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

    story.append(Paragraph("Program Notes".upper(), styles["subsection_heading"]))
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
    story.append(_section_header("Additional Notes", styles))
    story.append(Spacer(1, 8))
    # Build the "new vehicles only" line with the correct MY phrasing.
    # Previous version concatenated `eligible_models.split(' INEOS')[0]`
    # which returned "All model years" when no MY rule was set —
    # producing "untitled All model years model year vehicles". Now
    # builds from the actual rule list, omits the MY phrase entirely
    # when the program targets all years.
    my_codes = _rule_values(program, "model_year")
    if my_codes:
        my_phrase = ", ".join(my_codes) + " "
    else:
        my_phrase = ""
    additional = [
        f"<b>New vehicles only:</b> Offers apply only to new, untitled {my_phrase}INEOS Grenadier vehicles",
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
    story.append(_section_header("Quick Reference", styles))
    story.append(Spacer(1, 8))

    deal_types = stacking.get("deal_types", "Applied at point of sale")
    stackable_str = ", ".join(stacking.get("stackable_with", [])[:3]) if stacking.get("stackable_with") else "N/A"
    not_stackable_str = ", ".join(stacking.get("not_stackable_with", [])[:3]) if stacking.get("not_stackable_with") else "N/A"

    if excluded_programs:
        not_stackable_str = (
            (not_stackable_str + "; specifically: " + ", ".join(p.name for p in excluded_programs))
            if not_stackable_str != "N/A"
            else "specifically: " + ", ".join(p.name for p in excluded_programs)
        )

    # Quick Reference fields differ for vin_specific because Per-Unit
    # Amount is meaningless (each VIN has its own number) and Eligible
    # Models is replaced by the VIN-list summary.
    if program.program_type == "vin_specific" and vin_summary:
        if vin_summary.get("count"):
            lo = vin_summary.get("min_amount", 0)
            hi = vin_summary.get("max_amount", 0)
            if abs(lo - hi) < 0.01:
                amount_cell = f"${lo:,.0f} per VIN ({vin_summary['count']:,} VINs)"
            else:
                amount_cell = f"${lo:,.0f} \u2013 ${hi:,.0f} per VIN ({vin_summary['count']:,} VINs)"
        else:
            amount_cell = "VIN list not yet uploaded"
        qr_rows = [
            ("Program", program.name),
            ("Effective Period", f"{eff_short} \u2013 {exp_short}"),
            ("Eligibility", "Per-VIN list (see VIN Coverage)"),
            (type_title, amount_cell),
            ("Deal Types", deal_types),
            ("Stackable With", stackable_str),
            ("Not Stackable", not_stackable_str),
        ]
    else:
        qr_rows = [
            ("Program", program.name),
            ("Effective Period", f"{eff_short} \u2013 {exp_short}"),
            ("Eligible Models", eligible_models),
            (type_title, f"{amount_str} per vehicle"),
            ("Deal Types", deal_types),
            ("Stackable With", stackable_str),
            ("Not Stackable", not_stackable_str),
        ]
    # Use the same dynamic resolution as the IMPORTANT box so the Key
    # Rule cell never claims "fully stackable" when the matrix says
    # otherwise. Falls back to the boilerplate when nothing's wrong.
    key_rule_text = _compute_important_note(program, stacking, excluded_programs, live_not_stack)
    if key_rule_text:
        qr_rows.append(("Key Rule", key_rule_text))

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
        story.append(Paragraph(f"{type_title} Disclosure".upper(), styles["disclaimer_heading"]))
        story.append(Spacer(1, 4))

        if program.program_type == "vin_specific":
            # vin_specific can't print "$X (National) — MY25 ... MY26 ..."
            # because the amount varies by VIN. Disclosure has to be
            # framed in terms of the VIN list and the range.
            count = (vin_summary or {}).get("count", 0)
            lo = (vin_summary or {}).get("min_amount", 0)
            hi = (vin_summary or {}).get("max_amount", 0)
            if count and abs(lo - hi) < 0.01:
                amount_phrase = f"${lo:,.0f}"
            elif count:
                amount_phrase = f"${lo:,.0f}–${hi:,.0f}"
            else:
                amount_phrase = "varies"
            disclosure = (
                f"<b>{type_title} ({amount_phrase}) — Per-VIN Eligibility:</b> "
                f"Rebate is available only on the {count:,} specific VINs included in this "
                f"program from {eff_short} through {exp_short}. The rebate amount varies by "
                "VIN as published in the program's VIN list. "
                "Rebate must be applied toward the final transaction price. "
                "Not redeemable for cash. May not be combined with other incompatible offers. "
                "Customer must take delivery and sign all required documents during the program period. "
                "Additional taxes, fees, and dealer-installed equipment may apply. Offer valid only on the "
                "specific in-stock VINs published with this program; subject to change without notice. "
                "Additional restrictions may apply. INEOS Automotive Americas, LLC reserves the right to "
                "modify or terminate this program at any time. See retailer for full details."
            )
            story.append(Paragraph(disclosure, styles["disclaimer"]))
        else:
            # One consolidated disclosure paragraph that lists every eligible
            # MY x body combination at the top, then the boilerplate once. Was
            # previously N near-identical paragraphs (one per combo) which
            # bloated the bulletin to 3 pages of mostly-duplicate text.
            body_labels = [b.replace("_", " ").title() for b in (_rule_values(program, "body_style") or ["station_wagon", "quartermaster"])]
            my_labels = [m.replace("MY", "20") for m in (_rule_values(program, "model_year") or ["MY25", "MY26"])]
            combos = ", ".join(f"{my} INEOS Grenadier {bs}" for my in my_labels for bs in body_labels)
            not_apr_clause = " Not available with special APR or Retail Finance offers." if program.program_type == "customer_cash" else ""
            disclosure = (
                f"<b>{amount_str} {type_title} (National) — {combos}:</b> "
                f"Available on new models purchased {eff_short} through {exp_short}. "
                f"{type_title} must be applied toward the final transaction price.{not_apr_clause} "
                "Not redeemable for cash. May not be combined with other incompatible offers. "
                "Customer must take delivery and sign all required documents during the program period. "
                "Additional taxes, fees, and dealer-installed equipment may apply. Offer valid on in-stock "
                "vehicles only and subject to change without notice. Additional restrictions may apply. "
                "INEOS Automotive Americas, LLC reserves the right to modify or terminate this program at "
                "any time. See retailer for full details."
            )
            story.append(Paragraph(disclosure, styles["disclaimer"]))
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

    # Footer is painted by _on_page_footer (page-template callback) so
    # multi-page bulletins get correct page numbers — the previous
    # _footer_block flowable always said "Page 1" on every page.
    doc.build(story, onFirstPage=_on_page_footer, onLaterPages=_on_page_footer)
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
