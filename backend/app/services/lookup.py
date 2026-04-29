"""Retailer incentive lookup: match a deal configuration to a single campaign code."""

from sqlalchemy.orm import Session
from app.models.campaign_code import CampaignCode, CampaignCodeLayer
from app.models.program import Program, ProgramRule
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
        "cvp": "CVP",
        "demonstrator": "Demonstrator",
    }
    for pt in ["customer_cash", "apr_cash", "lease_cash", "cvp", "demonstrator"]:
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

    return LookupResponse(
        code=code.code,
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
        is_loyalty_or_conquest = prog.program_type in ("loyalty", "conquest")
        eval_config = dict(config)
        if is_loyalty_or_conquest:
            eval_config[prog.program_type] = True
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
    # Sort: auto-selected first (descending amount), then alternatives
    # (descending amount). Keeps the default stack at the top of the
    # chooser so the retailer's eye lands on what's already applied.
    eligible.sort(key=lambda e: (not e.auto_selected, -e.amount))
    return eligible
