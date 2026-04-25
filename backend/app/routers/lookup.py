from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.lookup import LookupRequest, LookupResponse
from app.services.lookup import lookup_incentive
from app.services.geo import zip_to_state, state_name, ALL_STATES, STATE_NAMES
from app.auth.security import get_current_user
from app.models.user import User
from app.models.vehicle import Vehicle

router = APIRouter(prefix="/api/lookup", tags=["lookup"])


@router.post("", response_model=LookupResponse)
def incentive_lookup(
    req: LookupRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Auto-resolve ZIP to state if ZIP provided but no state
    if req.zip_code and not req.state:
        resolved = zip_to_state(req.zip_code)
        if resolved:
            req.state = resolved

    result = lookup_incentive(db, req)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="No active incentive program for this configuration. Contact your RBM."
        )
    return result


@router.post("/public", response_model=LookupResponse)
def public_incentive_lookup(req: LookupRequest, db: Session = Depends(get_db)):
    """
    Phase 1 of the Incentive Dashboard rollout: a public, dealer-agnostic
    lookup powered by the same matching service as the authenticated path.
    No login required \u2014 the page behind it is shareable. Phase 2 will add a
    dealer-scoped variant that gates by retailer credentials.
    """
    # Drop any dealer-specific signal the caller may have supplied. The
    # public path is dealer-agnostic by definition; ignoring instead of
    # rejecting keeps the request shape identical to the authenticated
    # version so the same client form can target either endpoint.
    req.dealer_id = None
    if req.zip_code and not req.state:
        resolved = zip_to_state(req.zip_code)
        if resolved:
            req.state = resolved

    result = lookup_incentive(db, req)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="No active incentive program for this configuration. Contact your INEOS retailer."
        )
    return result


@router.get("/vin/{vin}")
def vin_lookup(vin: str, db: Session = Depends(get_db)):
    """Look up a VIN from the internal vehicle inventory (Master File).
    Falls back to basic VIN pattern decoding if not found in database."""
    vin = vin.strip().upper()

    # Search internal database first
    vehicle = db.query(Vehicle).filter(Vehicle.vin == vin).first()
    if vehicle:
        # Normalize trim to match product catalog / dropdown values
        trim = vehicle.trim or "Base"
        t = trim.upper()
        if "FIELDMASTER" in t: trim = "Fieldmaster"
        elif "BELSTAFF" in t or "BLACK EDITION" in t: trim = "Belstaff"
        elif "TRIALMASTER" in t: trim = "Trialmaster"
        elif "HIGHLANDS" in t: trim = "Highlands"
        elif "ARCANE" in t: trim = "Arcane Works Detour"
        elif "BASE" in t: trim = "Base"

        return {
            "vin": vehicle.vin,
            "model_year": vehicle.model_year,
            "body_style": vehicle.body_style,
            "trim": trim,
            "special_edition": vehicle.special_edition,
            "msrp": float(vehicle.msrp) if vehicle.msrp else None,
            "material": vehicle.material,
            "color_exterior": vehicle.color_exterior,
            "color_interior": vehicle.color_interior,
            "dealer_name": vehicle.dealer_name,
            "dealer_ship_to": vehicle.dealer_ship_to,
            "status": vehicle.status,
            "source": "inventory",
        }

    # Fallback: basic VIN pattern decode (INEOS VINs)
    # INEOS VINs start with SC6 (Station Wagon) or SH7 (Quartermaster)
    body_style = "station_wagon"
    if vin.startswith("SH7"):
        body_style = "quartermaster"

    # 10th character is model year: S=2025, T=2026, V=2027
    my_char = vin[9] if len(vin) >= 10 else ""
    my_map = {"S": "MY25", "T": "MY26", "V": "MY27", "R": "MY24"}
    model_year = my_map.get(my_char.upper())

    if model_year:
        return {
            "vin": vin,
            "model_year": model_year,
            "body_style": body_style,
            "trim": None,
            "special_edition": None,
            "msrp": None,
            "source": "vin_pattern",
        }

    raise HTTPException(
        status_code=404,
        detail="VIN not found in vehicle inventory. Verify the VIN or select vehicle details manually."
    )


@router.get("/zip/{zip_code}")
def zip_lookup(zip_code: str):
    """Resolve a ZIP code to a state abbreviation and name."""
    state = zip_to_state(zip_code)
    if not state:
        raise HTTPException(status_code=404, detail="Could not resolve ZIP code to a state")
    return {"zip_code": zip_code, "state": state, "state_name": state_name(state)}


@router.get("/msrp")
def get_msrp(
    model_year: str = "MY26",
    body_style: str = "station_wagon",
    trim: str = None,
    db: Session = Depends(get_db),
):
    """Get MSRP from the product catalog for a specific configuration."""
    from app.models.dealer import Product
    q = db.query(Product).filter(
        Product.model_year == model_year,
        Product.body_style == body_style,
        Product.active == True,
    )
    if trim:
        q = q.filter(Product.trim == trim)
    product = q.first()
    if not product or not product.msrp:
        return {"msrp": None}
    return {"msrp": float(product.msrp), "model_year": product.model_year,
            "body_style": product.body_style, "trim": product.trim}


@router.get("/rates")
def get_rates(
    model_year: str = "MY26",
    body_style: str = "station_wagon",
    trim: str = None,
    tier: int = 1,
):
    """Get Santander APR and lease rates for a vehicle configuration.
    Returns rates per term with trim-specific MF and residuals."""
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from app.services.santander_rates import (
        get_apr_for_config, get_lease_for_config, get_all_lease_by_trim
    )

    apr_rates = get_apr_for_config(base_dir, model_year, body_style, tier, trim)
    lease_rates = get_lease_for_config(base_dir, model_year, body_style, tier, trim)
    lease_by_trim = get_all_lease_by_trim(base_dir, model_year, body_style, tier)

    # Get mileage degradation from DB settings (or use defaults)
    from app.database import SessionLocal
    from app.models.budget import StackingRule
    db = SessionLocal()
    try:
        # Load mileage degradation config (stored as a stacking rule with deal_type='_mileage_degrade')
        degrade_rows = db.query(StackingRule).filter(
            StackingRule.deal_type == "_mileage_degrade"
        ).all()
        mileage_degradation = {}
        if degrade_rows:
            for r in degrade_rows:
                # program_type stores the mileage, allowed stores the degradation points
                mileage_degradation[r.program_type] = float(r.allowed)
        else:
            # Default mileage degradation table (residual points adjustment from 10k base)
            mileage_degradation = {
                "7500": 1,    # +1 point vs 10k
                "10000": 0,   # base (no adjustment)
                "12000": -1,  # -1 point
                "15000": -2,  # -2 points
            }
    finally:
        db.close()

    return {
        "model_year": model_year,
        "body_style": body_style,
        "trim": trim,
        "tier": tier,
        "apr": apr_rates,
        "lease": lease_rates,
        "lease_by_trim": lease_by_trim,
        "mileage_degradation": mileage_degradation,
    }


@router.get("/states")
def list_states():
    """Return all US states for dropdown population."""
    return [{"value": s, "label": f"{s} - {STATE_NAMES[s]}"} for s in ALL_STATES]
