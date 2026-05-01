"""Retailer incentive lookup: match a deal configuration to a single campaign code."""

from sqlalchemy.orm import Session
from app.models.campaign_code import CampaignCode, CampaignCodeLayer
from app.models.program import Program, ProgramRule, ProgramVin
from app.schemas.lookup import LookupRequest, LookupResponse, IncentiveLayer, EligibleProgram
from app.services.stacking import get_stacking_matrix
from app.services.code_matrix import is_program_applicable, program_matches_config


def _program_has_state_restriction(db: Session, program_id: str) -> list[str] | None:
    """Check if a program has a state restriction rule. Returns list of allowed states or None."""
    rule = db.query(ProgramRule).filter(
        ProgramRule.program_id == program_id,
        ProgramRule.rule_type == "state",
    ).first()
    if not rule:
        return None  # No state restriction = available everywhere
    val = rule.value
    if isinstance(val, list):
        return [str(s).upper() for s in val]
    return [str(val).upper()]


def lookup_incentive(db: Session, req: LookupRequest, public_only: bool = False) -> LookupResponse | None:
    """
    Find the single matching campaign code for a deal configuration.

    public_only — production gate. When True (only the unauthenticated
    /api/lookup/public path sets it), a code is returned only when EVERY
    contributing program is published=True. A staged program in any layer
    blocks the whole code from the public response so customers never see
    a number that admins haven't signed off on. Authenticated callers get
    the full staging+live view.
    """

    # Map finance_type to deal_type
    deal_type_map = {"cash": "cash", "apr": "apr", "lease": "lease"}
    deal_type = deal_type_map.get(req.finance_type, "cash")

    # Query matching code
    q = db.query(CampaignCode).filter(
        CampaignCode.active == True,
        CampaignCode.body_style == req.body_style,
        CampaignCode.deal_type == deal_type,
        CampaignCode.loyalty_flag == req.loyalty,
        CampaignCode.conquest_flag == req.conquest,
    )

    if req.model_year:
        q = q.filter(CampaignCode.model_year == req.model_year)

    if req.special_edition:
        q = q.filter(CampaignCode.special_flag == req.special_edition)
    else:
        q = q.filter(
            (CampaignCode.special_flag == None) | (CampaignCode.special_flag == "")
        )

    code = q.first()

    if not code:
        return None

    # Get layer breakdown, filtering out programs not available in the customer's state
    layers_data = (
        db.query(CampaignCodeLayer, Program)
        .join(Program, CampaignCodeLayer.program_id == Program.id)
        .filter(CampaignCodeLayer.campaign_code_id == code.id)
        .all()
    )

    # Production gate: if any contributing program is still staged
    # (published=False), the whole code stays out of the public response.
    # Returning None lets the router translate this to the same 404 the
    # caller would have seen pre-gate, so the public UI just shows
    # "no active program" instead of leaking that something exists in
    # staging.
    if public_only:
        if not all(getattr(prog, "published", False) for _, prog in layers_data):
            return None

    layers = []
    excluded_by_state = []
    customer_state = req.state.upper() if req.state else None

    for layer, prog in layers_data:
        # Check state restriction on the contributing program
        if customer_state:
            allowed_states = _program_has_state_restriction(db, prog.id)
            if allowed_states is not None and customer_state not in allowed_states:
                excluded_by_state.append({
                    "program_type": prog.program_type,
                    "label": prog.name,
                    "reason": f"Not available in {customer_state}",
                })
                continue

        layers.append(IncentiveLayer(
            program_name=prog.name,
            program_type=prog.program_type,
            amount=float(layer.layer_amount),
        ))

    # VIN-specific overlay on the auto-stacked layer set. These programs
    # aren't in the matrix (per-unit, not per-config), but when the VIN
    # is supplied and matches an active vin_specific program the rebate
    # IS part of the default stack — so it shows up in layers + counts
    # toward total_support_amount, not just the chooser.
    for prog, amount in _vin_specific_matches(db, req.vin, deal_type, public_only):
        if customer_state:
            allowed_states = _program_has_state_restriction(db, prog.id)
            if allowed_states is not None and customer_state not in allowed_states:
                excluded_by_state.append({
                    "program_type": prog.program_type,
                    "label": prog.name,
                    "reason": f"Not available in {customer_state}",
                })
                continue
        layers.append(IncentiveLayer(
            program_name=prog.name,
            program_type=prog.program_type,
            amount=amount,
        ))

    # Recalculate total from eligible layers only
    total_amount = sum(l.amount for l in layers)

    # Build "not applicable" list
    stacking = get_stacking_matrix(db)
    applicable_types = set(stacking.get(deal_type, []))
    not_applicable = list(excluded_by_state)  # Start with state-excluded programs

    type_labels = {
        "customer_cash": "Customer Cash",
        "apr_cash": "APR Cash",
        "lease_cash": "Lease Cash",
        "dealer_cash": "Dealer Cash",
        "cvp": "CVP",
        "demonstrator": "Demonstrator",
    }
    for pt in ["customer_cash", "apr_cash", "lease_cash", "dealer_cash", "cvp", "demonstrator"]:
        if pt not in applicable_types:
            not_applicable.append({
                "program_type": pt,
                "label": type_labels.get(pt, pt),
                "reason": f"Not applicable to {deal_type} deals",
            })

    if not req.loyalty:
        not_applicable.append({
            "program_type": "loyalty",
            "label": "Loyalty Rebate",
            "reason": "Customer not flagged as existing INEOS household",
        })
    if not req.conquest:
        not_applicable.append({
            "program_type": "conquest",
            "label": "Conquest Rebate",
            "reason": "No competitive trade-in indicated",
        })

    # Build the eligible-programs chooser. The matrix code's layers
    # are the auto-stacked default; eligible_programs enumerates ALL
    # programs that pass the config filters so the retailer can opt
    # any of them in or out (including programs the matrix dropped due
    # to per-program stacking conflicts). Each row carries the conflict
    # list so the UI can warn / disable on incompatible toggles.
    eligible_programs = _build_eligible_programs(
        db, deal_type, req, customer_state, layers_data, public_only,
    )

    # Base "no incentives" code for this (body x MY x deal_type). The
    # frontend swaps the chip to this when the customer takes none of
    # the available auto-stacked programs — distinct from the bundled
    # code so SAP correctly records the no-incentive deal. Matched by
    # body+MY+deal_type with loyalty/conquest/special all false/null
    # and the support_amount = 0 (every base row in the matrix).
    base_code_row = (
        db.query(CampaignCode)
        .filter(
            CampaignCode.active == True,
            CampaignCode.body_style == req.body_style,
            CampaignCode.deal_type == deal_type,
            CampaignCode.loyalty_flag == False,  # noqa: E712
            CampaignCode.conquest_flag == False,  # noqa: E712
            CampaignCode.support_amount == 0,
            (CampaignCode.special_flag == None) | (CampaignCode.special_flag == ""),  # noqa: E711
            CampaignCode.code.like("%Z"),
        )
    )
    if req.model_year:
        base_code_row = base_code_row.filter(CampaignCode.model_year == req.model_year)
    base_code_row = base_code_row.first()

    # Per-restricted-eligibility variant codes. The matrix builder
    # emits a one-layer row per (body x MY x deal_type) where each
    # restricted program qualifies. Frontend uses this to swap the
    # chip to USLSTE / USLSTF / etc. when the user toggles DEL or F&F
    # in the chooser. Map keyed on program_id so the frontend's
    # selection-by-id maps cleanly to a code.
    restricted_codes: dict[str, str] = {}
    elig_rows = (
        db.query(CampaignCode, CampaignCodeLayer)
        .join(CampaignCodeLayer, CampaignCode.id == CampaignCodeLayer.campaign_code_id)
        .filter(
            CampaignCode.active == True,
            CampaignCode.body_style == req.body_style,
            CampaignCode.deal_type == deal_type,
            CampaignCode.loyalty_flag == False,  # noqa: E712
            CampaignCode.conquest_flag == False,  # noqa: E712
            (CampaignCode.special_flag == None) | (CampaignCode.special_flag == ""),  # noqa: E711
            ~CampaignCode.code.like("%Z"),  # exclude base codes
            ~CampaignCode.code.like("%L"),  # exclude loyalty
            ~CampaignCode.code.like("%C"),  # exclude conquest
            ~CampaignCode.code.like("%B"),  # exclude both
        )
    )
    if req.model_year:
        elig_rows = elig_rows.filter(CampaignCode.model_year == req.model_year)
    for cc, layer in elig_rows.all():
        # Variant codes have exactly one layer (the restricted
        # program). Use that program_id as the key.
        restricted_codes[layer.program_id] = cc.code

    return LookupResponse(
        code=code.code,
        base_code=base_code_row.code if base_code_row else None,
        restricted_codes=restricted_codes,
        total_support_amount=total_amount,
        label=code.label or "",
        layers=layers,
        not_applicable=not_applicable,
        eligible_programs=eligible_programs,
        model_year=req.model_year,
        body_style=req.body_style,
        deal_type=deal_type,
        loyalty=req.loyalty,
        conquest=req.conquest,
    )


def _vin_specific_matches(db: Session, vin: str | None, deal_type: str,
                          public_only: bool) -> list[tuple[Program, float]]:
    """Find every active vin_specific program whose VIN list covers the
    requested VIN. Returns (program, per_vin_amount) pairs. Empty list
    when no VIN was supplied or no program covers it.

    vin_specific programs are excluded from the campaign-code matrix
    because they're per-unit (not per-config), so this is the only
    place they enter the response. The amount comes from the matching
    ProgramVin row, NOT from Program.per_unit_amount."""
    if not vin:
        return []
    vin_clean = vin.strip().upper()
    if not vin_clean:
        return []
    rows = (
        db.query(ProgramVin, Program)
        .join(Program, ProgramVin.program_id == Program.id)
        .filter(
            ProgramVin.vin == vin_clean,
            Program.status == "active",
            Program.program_type == "vin_specific",
        )
        .all()
    )
    if public_only:
        rows = [(pv, prog) for pv, prog in rows if getattr(prog, "published", False)]
    # Honor the stacking matrix at the deal-type level — admins can
    # disable vin_specific for, say, lease deals via the matrix even
    # though the default is allow-all.
    stacking = get_stacking_matrix(db)
    rows = [
        (pv, prog) for pv, prog in rows
        if is_program_applicable(deal_type, prog.program_type, stacking)
    ]
    return [(prog, float(pv.amount)) for pv, prog in rows]


def _build_eligible_programs(db: Session, deal_type: str, req, customer_state, layers_data, public_only: bool) -> list[EligibleProgram]:
    # Reproduce the matching logic from code_matrix.rebuild_matrix so
    # the chooser sees every program that COULD apply, not just the
    # ones the matrix bundled. We deliberately re-derive instead of
    # querying the matrix code's layers because the matrix already
    # resolves conflicts (drops the lower-amount program) — and the
    # retailer needs to see the dropped program as a togglable
    # alternative.
    config = {
        "body_style": req.body_style,
        "model_year": req.model_year,
        "finance_type": deal_type,
        "loyalty": bool(req.loyalty),
        "conquest": bool(req.conquest),
        "special_edition": req.special_edition,
    }
    stacking = get_stacking_matrix(db)
    active_programs = db.query(Program).filter(Program.status == "active").all()
    if public_only:
        active_programs = [p for p in active_programs if getattr(p, "published", False)]

    auto_ids = {prog.id for _, prog in layers_data}
    eligible: list[EligibleProgram] = []
    for prog in active_programs:
        # vin_specific programs go through the dedicated VIN matcher
        # below — never via the per-config rule matcher (they have no
        # body_style / model_year rules; eligibility is solely the
        # VIN list).
        if prog.program_type == "vin_specific":
            continue
        if not is_program_applicable(deal_type, prog.program_type, stacking):
            continue
        # Loyalty/conquest programs need to appear in the chooser as
        # opt-in alternatives even when the corresponding flag is false
        # — otherwise the user has no way to reach the loyalty/conquest
        # variant of the campaign code (USCSWSL, USCSWSC, USCSWSLC).
        # We re-evaluate the program's other rules with the flag forced
        # on so it passes its own rules; the actual flag the lookup is
        # called with comes back to false in the response, and the
        # frontend re-issues the lookup with the right flag when the
        # user opts the program in.
        # Match on type primarily, but also fall back to the program
        # name — admins sometimes type a Loyalty/Conquest program as
        # bonus_cash because the rebate funding is the same. The
        # campaign-code variant still needs the L/C flag either way.
        name_lc = (prog.name or "").lower()
        effective_type = None
        if prog.program_type == "loyalty" or "loyalty" in name_lc:
            effective_type = "loyalty"
        elif prog.program_type == "conquest" or "conquest" in name_lc:
            effective_type = "conquest"
        eval_config = dict(config)
        if effective_type:
            eval_config[effective_type] = True
        if not program_matches_config(prog, eval_config):
            continue
        # State-restriction filter — the program is removed entirely
        # from the chooser (rather than shown disabled) because it
        # genuinely doesn't apply to this customer.
        if customer_state:
            allowed_states = _program_has_state_restriction(db, prog.id)
            if allowed_states is not None and customer_state not in allowed_states:
                continue
        eligible.append(EligibleProgram(
            program_id=prog.id,
            program_name=prog.name,
            program_type=prog.program_type,
            amount=float(prog.per_unit_amount or 0),
            auto_selected=(prog.id in auto_ids),
            conflicts_with=list(getattr(prog, "not_stackable_program_ids", None) or []),
        ))

    # vin_specific overlay — add a row per matching program with the
    # VIN-specific dollar amount and auto_selected=True (the whole
    # premise of vin_specific is "this VIN was pre-targeted, surface
    # the rebate"). The retailer can still untoggle it on the chooser.
    for prog, amount in _vin_specific_matches(db, req.vin, deal_type, public_only):
        if customer_state:
            allowed_states = _program_has_state_restriction(db, prog.id)
            if allowed_states is not None and customer_state not in allowed_states:
                continue
        eligible.append(EligibleProgram(
            program_id=prog.id,
            program_name=prog.name,
            program_type=prog.program_type,
            amount=amount,
            auto_selected=True,
            conflicts_with=list(getattr(prog, "not_stackable_program_ids", None) or []),
        ))

    # Sort: auto-selected first (descending amount), then alternatives
    # (descending amount). Keeps the default stack at the top of the
    # chooser so the retailer's eye lands on what's already applied.
    eligible.sort(key=lambda e: (not e.auto_selected, -e.amount))
    return eligible
