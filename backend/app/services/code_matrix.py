"""
Combinatorial Campaign Code Matrix Engine.

This is the CORE of the IMS. It generates the full campaign code matrix
by enumerating all valid deal configurations and computing composite
incentive amounts from active programs + stacking rules.

ONE CODE = ONE COMPLETE DEAL CONFIGURATION.
"""

from itertools import product as iterproduct
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models.program import Program, ProgramRule
from app.models.campaign_code import CampaignCode, CampaignCodeLayer
from app.models.dealer import Product
from app.services.stacking import get_stacking_matrix, is_program_applicable


# --- Code naming convention (HARD 6-character SAP cap) ---
#
# SAP refuses anything longer than 6 characters, so every variant has
# to fit. Letters only (no digits). Layout:
#
#   US + dt(1) + body(1) + my(1) + flag(0-1) = 5 or 6 chars
#
#   dt    : C(ash) / A(pr) / L(ease) / V(=cVp) / D(emo)
#   body  : S(W) / Q(M) / A(rcane works G13C body)
#   my    : R=24 / S=25 / T=26 / V=27 (matches the VIN's 10th char)
#   flag  : L=loyalty only, C=conquest only, B=both. Empty otherwise.
#
# Examples:
#   USCSS   = Cash, SW, MY25, base
#   USCSSL  = Cash, SW, MY25, +Loyalty
#   USCSSC  = Cash, SW, MY25, +Conquest
#   USCSSB  = Cash, SW, MY25, +Loyalty +Conquest
#   USCST   = Cash, SW, MY26, base
#   USCQS   = Cash, QM, MY25, base
#   USCAS   = Cash, Arcane Works (G13C body), MY25
#   USAAS   = APR  Arcane MY25
#   USVSS   = CVP  SW MY25  (CVP/Demo never carry loyalty/conquest)
#   USDQT   = Demo QM MY26
#
# A previous iteration of this file used 2-char body abbreviations
# (SW/QM/AW) which forced MAX_CODE_LEN to 12 to fit loyalty+conquest
# combos. SAP rejected those longer codes, so we collapsed body to a
# single letter and traded the LC suffix for a single B (both)
# letter. The compact scheme is what production has always used in
# spirit (USSW / USSWL / USSWD / USSWLD); this just extends it
# uniformly to all body/deal-type/MY combinations.
MAX_CODE_LEN = 6


# Model year → VIN-standard 10th-character letter. Matches the VIN
# decoding table in routers/lookup.vin_lookup so the MY letter in a
# campaign code is the same letter a retailer would read off the VIN.
MY_TO_LETTER = {
    "MY24": "R",
    "MY25": "S",
    "MY26": "T",
    "MY27": "V",  # skips U per VIN standard
    "MY28": "W",
    "MY29": "X",
    "MY30": "Y",
}


# Single-letter body codes used inside the campaign-code string.
# A = Arcane Works (G13C body — distinct from SW because it has its
# own SAP material code and rate sheet).
_BODY_LETTER = {
    "station_wagon": "S",
    "quartermaster": "Q",
    "arcane_works":  "A",
}

# Single-letter deal-type prefix.
_DT_LETTER = {
    "cash":  "C",
    "apr":   "A",
    "lease": "L",
    "cvp":   "V",
    "demo":  "D",
}


def _flag_letter(loyalty: bool, conquest: bool) -> str:
    """L (loyalty only), C (conquest only), B (both), or empty.
    'B' (both) is used because LC would push the code to 7 characters,
    which SAP rejects. The flag letter is parsed by position (last
    char) so 'C' there is unambiguous despite 'C' also being the
    cash deal-type letter at position 3."""
    if loyalty and conquest:
        return "B"
    if loyalty:
        return "L"
    if conquest:
        return "C"
    return ""


# Program-name keywords that mark a program as restricted-eligibility
# (only applies when the customer specifically qualifies — dealer
# employee, friends/family/business partner, Costco affiliate, etc.).
# These programs are excluded from the default matrix bundle so the
# campaign code's default total reflects what every customer in the
# config can actually take. They still appear as opt-in choices in
# the chooser via _build_eligible_programs and contribute when the
# user explicitly toggles them on.
_RESTRICTED_ELIGIBILITY_KEYWORDS = (
    "dealer employee",
    "employee lease",
    "friends",
    "family",
    "business partner",
    "affiliate",
    "costco",
    "supplier",
)


def _is_restricted_eligibility(program) -> bool:
    """Detect whether a program has restricted eligibility (dealer
    employee, friends/family, etc.) by name. Used to exclude these
    programs from the default matrix bundle so the headline campaign-
    code total only reflects programs every customer can take."""
    name = (getattr(program, "name", None) or "").lower()
    return any(kw in name for kw in _RESTRICTED_ELIGIBILITY_KEYWORDS)


def generate_code_string(body_style: str, model_year: str, deal_type: str,
                         loyalty: bool, conquest: bool, special: str | None,
                         base: bool = False) -> str:
    """Generate the 6-char-max SAP campaign code for a deal config.

    `special` is no longer used to vary the code string — Arcane Works
    is its own body_style and Iceland Tactical (still a SW trim
    package) shares SW codes. Per-program eligibility filtering still
    happens at the program-rule layer, so an Iceland-targeted program
    only attaches to the SW codes it qualifies for.

    `base=True` returns the base/no-incentive code for the (body x MY x
    deal_type) combo — distinct from the auto-stacked code that gets
    emitted when programs match. Suffix Z marks "Zero programs" so a
    dealer entering a deal where the customer takes none of the
    available programs has a clean SAP code to use. Z doesn't collide
    with the L/C/B flag letters used on stacked variants.
    """
    body_letter = _BODY_LETTER.get(body_style, "S")
    my_letter = MY_TO_LETTER.get(model_year or "", "")
    dt_letter = _DT_LETTER.get(deal_type, "C")

    if base:
        # Base codes never carry loyalty/conquest flags — they
        # represent the "no incentives selected" baseline, period.
        return f"US{dt_letter}{body_letter}{my_letter}Z"[:MAX_CODE_LEN]

    # CVP and Demo never carry loyalty/conquest flags — they're
    # standalone retail channels by convention. Skip the flag suffix
    # so the matrix dedup doesn't emit redundant L/C variants.
    if deal_type in ("cvp", "demo"):
        flag = ""
    else:
        flag = _flag_letter(loyalty, conquest)

    code = f"US{dt_letter}{body_letter}{my_letter}{flag}"
    # Final guardrail — should never trigger given the layout above,
    # but truncating beats producing a code SAP rejects mid-deal.
    return code[:MAX_CODE_LEN]


def evaluate_rule(rule: ProgramRule, config: dict) -> bool:
    """Evaluate a single program rule against a deal configuration."""
    rule_type = rule.rule_type
    op = rule.operator
    val = rule.value

    config_val = config.get(rule_type)
    if config_val is None:
        if op in ("not_equals", "not_in"):
            return True
        return False

    if op == "equals":
        return str(config_val) == str(val)
    elif op == "not_equals":
        return str(config_val) != str(val)
    elif op == "in":
        if isinstance(val, list):
            return str(config_val) in [str(v) for v in val]
        return str(config_val) == str(val)
    elif op == "not_in":
        if isinstance(val, list):
            return str(config_val) not in [str(v) for v in val]
        return str(config_val) != str(val)
    elif op == "gte":
        try:
            return float(config_val) >= float(val)
        except (ValueError, TypeError):
            return False
    elif op == "lte":
        try:
            return float(config_val) <= float(val)
        except (ValueError, TypeError):
            return False
    elif op == "between":
        try:
            v = float(config_val)
            return float(val.get("min", 0)) <= v <= float(val.get("max", 999999))
        except (ValueError, TypeError, AttributeError):
            return False
    return False


def program_matches_config(program: Program, config: dict) -> bool:
    """Check if all rules of a program match the deal configuration (AND logic)."""
    for rule in program.rules:
        if not evaluate_rule(rule, config):
            return False
    return True


def build_configuration_space(db: Session) -> list[dict]:
    """Enumerate all valid deal configurations from the product catalog."""
    products = db.query(Product).filter(Product.active == True).all()

    body_styles = set()
    model_years = set()
    trims = set()
    specials = set()

    for p in products:
        body_styles.add(p.body_style)
        model_years.add(p.model_year)
        trims.add(p.trim)
        if p.special_edition:
            specials.add(p.special_edition)

    if not body_styles:
        body_styles = {"station_wagon", "quartermaster", "arcane_works"}
    else:
        # Always cover the three known body codes so the matrix can
        # emit codes for them even when the product catalog is sparse
        # (e.g. before someone seeds an Arcane Works product row).
        body_styles |= {"station_wagon", "quartermaster", "arcane_works"}
    if not model_years:
        model_years = {"MY25", "MY26"}

    deal_types = ["cash", "apr", "lease", "cvp", "demo"]
    loyalty_flags = [False, True]
    conquest_flags = [False, True]
    special_list = [None] + list(specials)

    configs = []
    for body, my, dt, loy, conq, sp in iterproduct(
        sorted(body_styles), sorted(model_years), deal_types,
        loyalty_flags, conquest_flags, special_list
    ):
        # CVP and Demo don't have loyalty+conquest combos in most cases
        if dt in ("cvp", "demo") and (loy or conq):
            continue
        configs.append({
            "body_style": body,
            "model_year": my,
            "finance_type": dt,
            "loyalty": loy,
            "conquest": conq,
            "special_edition": sp,
        })
    return configs


def rebuild_matrix(db: Session, preview_only: bool = False) -> list[dict]:
    """
    Rebuild the entire campaign code matrix from active programs + stacking rules.
    Returns list of matrix diff items.
    """
    active_programs = db.query(Program).filter(
        Program.status == "active"
    ).all()

    stacking = get_stacking_matrix(db)
    configs = build_configuration_space(db)

    # Get existing codes for diff
    existing_codes = {}
    for code in db.query(CampaignCode).all():
        existing_codes[code.code] = code

    new_matrix = []

    for config in configs:
        deal_type = config["finance_type"]
        matching_layers = []

        for prog in active_programs:
            # vin_specific programs are per-unit (not per-config), so
            # they NEVER enter the matrix. Their layers are added at
            # lookup time from ProgramVin rows that match the request's
            # VIN. Including them here would (a) attach a phantom
            # 0-dollar layer to every matrix code and (b) double-count
            # when the lookup path then adds the real VIN amount.
            if prog.program_type == "vin_specific":
                continue
            # Restricted-eligibility programs (Dealer Employee, F&F,
            # Costco, etc.) are opt-in by definition — most customers
            # can't claim them. Bundling them into the default matrix
            # code's stack would inflate the headline total and mislead
            # SAP into recording programs the customer didn't actually
            # take. They still surface as opt-in choices in the chooser
            # via _build_eligible_programs, so the dealer can stack
            # them when the customer qualifies.
            if _is_restricted_eligibility(prog):
                continue
            if not is_program_applicable(deal_type, prog.program_type, stacking):
                continue
            if not program_matches_config(prog, config):
                continue
            # Loyalty/conquest gate. Match on type primarily, but also
            # fall back to the program name — admins sometimes type a
            # Loyalty/Conquest program as bonus_cash because the
            # rebate funding is the same. The campaign-code variant
            # (USCSWSL / USCSWSC / USCSWSB) needs the L/C bit either
            # way, so the gate has to recognize both signals.
            name_lc = (prog.name or "").lower()
            is_loyalty = prog.program_type == "loyalty" or "loyalty" in name_lc
            is_conquest = prog.program_type == "conquest" or "conquest" in name_lc
            if is_loyalty and not config["loyalty"]:
                continue
            if is_conquest and not config["conquest"]:
                continue
            matching_layers.append({
                "program_id": prog.id,
                "program_name": prog.name,
                "program_type": prog.program_type,
                "amount": float(prog.per_unit_amount or 0),
            })

        # Per-program stacking enforcement. The wizard's "Not Stackable
        # With" control writes program ids onto Program.not_stackable_
        # program_ids; this check honors them by dropping the lower-
        # amount layer of any incompatible pair. Symmetric: a single
        # admin marking A.not_stackable=[B] is enough — they don't
        # have to also flip B.not_stackable=[A].
        if matching_layers:
            prog_by_id = {p.id: p for p in active_programs}
            keep = list(range(len(matching_layers)))
            removed = set()
            for i in range(len(matching_layers)):
                if i in removed:
                    continue
                a_layer = matching_layers[i]
                a_prog = prog_by_id.get(a_layer["program_id"])
                a_excl = set(getattr(a_prog, "not_stackable_program_ids", None) or [])
                for j in range(i + 1, len(matching_layers)):
                    if j in removed:
                        continue
                    b_layer = matching_layers[j]
                    b_prog = prog_by_id.get(b_layer["program_id"])
                    b_excl = set(getattr(b_prog, "not_stackable_program_ids", None) or [])
                    if b_layer["program_id"] in a_excl or a_layer["program_id"] in b_excl:
                        # Drop the lower-amount layer; on a tie keep
                        # the one declared first (deterministic).
                        loser = j if a_layer["amount"] >= b_layer["amount"] else i
                        removed.add(loser)
                        if loser == i:
                            break  # i is gone; stop pairing it
            if removed:
                matching_layers = [l for k, l in enumerate(matching_layers) if k not in removed]

        total_amount = sum(l["amount"] for l in matching_layers)

        # Always emit a base code for cash / apr / lease / demo even
        # when no programs contribute, so the retailer has a SAP code
        # to enter for the deal type regardless of incentive coverage.
        # Skip only:
        #   • cvp configs with no matching cvp program (the code
        #     itself only makes sense when a CVP program applies),
        #   • special-edition configs with no matching program (no
        #     sensible "default" exists for an Arcane / Iceland code).
        if total_amount == 0:
            if deal_type == "cvp":
                continue
            if config.get("special_edition"):
                continue

        # Loyalty / conquest gate. The outer loop generates configs for
        # every combination of loyalty and conquest flags, but those
        # flags are only meaningful if a matching loyalty/conquest
        # program is actually contributing. Without that, the base
        # programs (customer_cash, lease_cash, etc.) still match the
        # config and we'd emit a code that claims loyalty/conquest
        # applies while paying the exact same amount as the non-
        # loyalty / non-conquest version. Skip those — they'd just be
        # noise in the matrix and the public lookup.
        # Match on type primarily, but also fall back to the program
        # name (case-insensitive) — a "Loyalty" program typed as
        # bonus_cash should still satisfy this gate so the L variant
        # gets emitted.
        def _has_layer(kind: str) -> bool:
            for l in matching_layers:
                if l["program_type"] == kind:
                    return True
                if kind in (l.get("program_name") or "").lower():
                    return True
            return False
        if config["loyalty"] and not _has_layer("loyalty"):
            continue
        if config["conquest"] and not _has_layer("conquest"):
            continue

        code_str = generate_code_string(
            config["body_style"], config["model_year"], deal_type,
            config["loyalty"], config["conquest"], config.get("special_edition")
        )

        # Determine change type
        existing = existing_codes.get(code_str)
        if existing:
            current_amt = float(existing.support_amount or 0)
            if abs(current_amt - total_amount) < 0.01:
                change_type = "unchanged"
            else:
                change_type = "changed"
        else:
            change_type = "new"
            current_amt = None

        # Build label
        parts = []
        if config.get("special_edition"):
            parts.append(config["special_edition"].replace("_", " ").title())
        parts.append(config["model_year"])
        parts.append(config["body_style"].replace("_", " ").title())
        parts.append(deal_type.upper())
        if config["loyalty"]:
            parts.append("+ Loyalty")
        if config["conquest"]:
            parts.append("+ Conquest")
        label = " ".join(parts)

        new_matrix.append({
            "code": code_str,
            "label": label,
            "model_year": config["model_year"],
            "body_style": config["body_style"],
            "deal_type": deal_type,
            "loyalty_flag": config["loyalty"],
            "conquest_flag": config["conquest"],
            "special_flag": config.get("special_edition"),
            "current_amount": current_amt,
            "new_amount": total_amount,
            "change_type": change_type,
            "layers": matching_layers,
            "effective_date": None,
            "expiration_date": None,
        })

    # ── Base / no-incentive codes ──
    #
    # Always emit a base $0 code per (body x MY x cash/apr/lease/demo)
    # combo regardless of which programs match. Distinct code string
    # (Z suffix) so the dealer has something to enter in SAP when the
    # customer takes none of the available auto-stacked programs. CVP
    # is excluded — it's a standalone channel and the matrix only
    # makes a CVP code when a specific CVP program applies.
    base_emitted: set[str] = set()
    for config in configs:
        deal_type = config["finance_type"]
        if deal_type == "cvp":
            continue
        if config["loyalty"] or config["conquest"] or config.get("special_edition"):
            continue
        base_code = generate_code_string(
            config["body_style"], config["model_year"], deal_type,
            False, False, None, base=True,
        )
        if base_code in base_emitted:
            continue
        base_emitted.add(base_code)
        body_label = "Arcane Works" if config["body_style"] == "arcane_works" else config["body_style"].replace("_", " ").title()
        label = f"{config['model_year']} {body_label} {deal_type.upper()} (Base — no incentives)"
        new_matrix.append({
            "code": base_code,
            "label": label,
            "model_year": config["model_year"],
            "body_style": config["body_style"],
            "deal_type": deal_type,
            "loyalty_flag": False,
            "conquest_flag": False,
            "special_flag": None,
            "current_amount": None,
            "new_amount": 0.0,
            "change_type": "new",
            "layers": [],
            "effective_date": None,
            "expiration_date": None,
        })

    if preview_only:
        return new_matrix

    # Apply: delete old codes and create new ones
    db.query(CampaignCodeLayer).delete()
    db.query(CampaignCode).delete()

    seen_codes = {}
    for item in new_matrix:
        # Dedup on the FULL code string. Truncating to 6 was a relic
        # from when MAX_CODE_LEN was 6 and base/loyalty/conquest
        # variants for the same body+MY+deal happened to share a
        # 6-char prefix (e.g. USCSWS base vs USCSWSL loyalty both
        # hashed to "USCSWS"). The truncation silently dropped the
        # variants — first iteration won, the rest disappeared.
        code_str = item["code"]
        if code_str in seen_codes:
            continue
        seen_codes[code_str] = item

        # Get date range from contributing programs
        eff_date = None
        exp_date = None
        for prog in active_programs:
            if any(l["program_id"] == prog.id for l in item["layers"]):
                if eff_date is None or prog.effective_date < eff_date:
                    eff_date = prog.effective_date
                if exp_date is None or prog.expiration_date > exp_date:
                    exp_date = prog.expiration_date

        cc = CampaignCode(
            code=code_str,
            label=item["label"],
            support_amount=Decimal(str(item["new_amount"])),
            model_year=item["model_year"],
            body_style=item["body_style"],
            deal_type=item["deal_type"],
            loyalty_flag=item["loyalty_flag"],
            conquest_flag=item["conquest_flag"],
            special_flag=item.get("special_flag"),
            active=True,
            effective_date=eff_date,
            expiration_date=exp_date,
        )
        db.add(cc)
        db.flush()

        for layer in item["layers"]:
            db.add(CampaignCodeLayer(
                campaign_code_id=cc.id,
                program_id=layer["program_id"],
                layer_amount=Decimal(str(layer["amount"])),
            ))

    db.commit()
    return new_matrix
