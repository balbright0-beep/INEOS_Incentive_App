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


# --- Code naming convention (6-character max, matching production) ---
#
# ONE code per deal at SAP handover. Max 6 characters.
# The code encodes: country + body/deal + MY variant + loyalty/conquest overlays
#
# Production examples:
#   CASH:  USSW, USSWL, USFNF, USFNFL, USQM, USQML, USFNQM, USFNQL
#   MY26:  USSWD, USSWLD, USFND, USFNFD, USQMD, USQMLD, USFNQD, USFDQL
#   APR:   USAPSW, USAPSL, USASFN, USALNS, USAPQM, USAPQL, USAQFN, USALNQ
#   LEASE: USLESW, USLESL, USLFNS, USLLNS, USLEEL, USLLEL
#   OTHER: USARDC, USARDL, USCVP, USDEMO

# Bumped from 6 → 10 so APR/Lease/etc codes can carry a model-year
# suffix without colliding. Codes were previously truncated to 6,
# which meant USAPSW (APR Station Wagon) was the same string for
# MY25 and MY26 — the matrix builder's dedup kept whichever ran
# first and silently dropped the other, so the retailer lookup for
# MY26 SW returned 404. Existing 6-char codes (USCAQM, USLESW)
# stay valid; new codes can grow.
MAX_CODE_LEN = 10


# Model year → VIN-standard 10th-character letter. Lines up with the
# decoding table in lookup.vin_lookup so a code's MY suffix matches
# the letter a retailer would see in the VIN itself. Letters only
# (no digits anywhere in campaign codes — SAP requirement).
MY_TO_LETTER = {
    "MY24": "R",
    "MY25": "S",
    "MY26": "T",
    "MY27": "V",  # skips U per VIN standard
    "MY28": "W",
    "MY29": "X",
    "MY30": "Y",
}


def generate_code_string(body_style: str, model_year: str, deal_type: str,
                         loyalty: bool, conquest: bool, special: str | None) -> str:
    """
    Generate a campaign code string. Letters only — no digits — so
    SAP accepts the code. MY25 / MY26 / MY27 produce distinct codes
    via the MY_TO_LETTER mapping (S / T / V), matching the VIN-MY
    convention so the suffix is mnemonic rather than arbitrary.

    Format: <prefix><body><my_letter>[<flags>].
    """

    is_qm = body_style == "quartermaster"
    body_short = "QM" if is_qm else "SW"

    # MY letter (S / T / V / ...) — required so different model years
    # never collide on the same code string. Falls back to "" when MY
    # is missing or unmapped, which keeps the function pure but means
    # the matrix dedup will collapse cross-MY codes for unknown years.
    my_letter = MY_TO_LETTER.get(model_year or "", "")

    # ── Special editions (Arcane Works, Iceland Tactical) ──
    if special:
        sp_map = {"arcane_works_detour": "ARD", "iceland_tactical": "ICE"}
        sp = sp_map.get(special, special[:3].upper())
        base = f"US{sp}{my_letter}"
        if loyalty:
            return f"{base}L"[:MAX_CODE_LEN]
        return f"{base}C"[:MAX_CODE_LEN]

    # ── CVP ──  USCVP + body + my  (e.g. USCVPSWT, USCVPQMS)
    # Body must appear in the code, otherwise SW and QM collapse to
    # the same string and the matrix dedup drops one — that was the
    # cause of the missing station-wagon CVP code.
    if deal_type == "cvp":
        return f"USCVP{body_short}{my_letter}"[:MAX_CODE_LEN]

    # ── Demonstrator ──  USDEM + body + my  (same dedup reason)
    if deal_type == "demo":
        return f"USDEM{body_short}{my_letter}"[:MAX_CODE_LEN]

    flag_suffix = ""
    if loyalty and conquest:
        flag_suffix = "LC"
    elif loyalty:
        flag_suffix = "L"
    elif conquest:
        flag_suffix = "C"

    # ── Cash deals ──  USC + body + my + flags  (e.g. USCSWT, USCQMTL, USCSWSLC)
    if deal_type == "cash":
        return f"USC{body_short}{my_letter}{flag_suffix}"[:MAX_CODE_LEN]

    # ── APR deals ──  USA + body + my + flags  (e.g. USASWT, USAQMTL)
    if deal_type == "apr":
        return f"USA{body_short}{my_letter}{flag_suffix}"[:MAX_CODE_LEN]

    # ── Lease deals ──  USL + body + my + flags  (e.g. USLSWT, USLQMTL)
    if deal_type == "lease":
        return f"USL{body_short}{my_letter}{flag_suffix}"[:MAX_CODE_LEN]

    # Fallback
    return f"US{body_short}{my_letter}"[:MAX_CODE_LEN]


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
        body_styles = {"station_wagon", "quartermaster"}
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
            if not is_program_applicable(deal_type, prog.program_type, stacking):
                continue
            if not program_matches_config(prog, config):
                continue
            # Loyalty/conquest program types only apply if the flag is set
            if prog.program_type == "loyalty" and not config["loyalty"]:
                continue
            if prog.program_type == "conquest" and not config["conquest"]:
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
        if config["loyalty"] and not any(l["program_type"] == "loyalty" for l in matching_layers):
            continue
        if config["conquest"] and not any(l["program_type"] == "conquest" for l in matching_layers):
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

    if preview_only:
        return new_matrix

    # Apply: delete old codes and create new ones
    db.query(CampaignCodeLayer).delete()
    db.query(CampaignCode).delete()

    seen_codes = {}
    for item in new_matrix:
        code_str = item["code"][:6]  # Enforce 6-char max
        if code_str in seen_codes:
            # Duplicate code = same deal configuration already covered. Skip it.
            # This happens when multiple special editions map to the same code pattern.
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
