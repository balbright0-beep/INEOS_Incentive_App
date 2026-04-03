"""Retailer incentive lookup: match a deal configuration to a single campaign code."""

from sqlalchemy.orm import Session
from app.models.campaign_code import CampaignCode, CampaignCodeLayer
from app.models.program import Program, ProgramRule
from app.schemas.lookup import LookupRequest, LookupResponse, IncentiveLayer
from app.services.stacking import get_stacking_matrix


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


def lookup_incentive(db: Session, req: LookupRequest) -> LookupResponse | None:
    """Find the single matching campaign code for a deal configuration."""

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

    return LookupResponse(
        code=code.code,
        total_support_amount=total_amount,
        label=code.label or "",
        layers=layers,
        not_applicable=not_applicable,
        model_year=req.model_year,
        body_style=req.body_style,
        deal_type=deal_type,
        loyalty=req.loyalty,
        conquest=req.conquest,
    )
