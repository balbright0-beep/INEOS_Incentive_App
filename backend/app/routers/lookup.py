from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.lookup import (
    LookupRequest, LookupResponse,
    PreviewRequest, PreviewResponse, DealTypePreview,
)
from app.services.lookup import lookup_incentive
from app.services.geo import (
    zip_to_state, state_name, state_tax_rate, zip_to_combined_tax_rate,
    state_lease_tax_basis,
    ALL_STATES, STATE_NAMES,
)
from app.services import platform_client
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

    # public_only=True enforces the production gate: codes whose layers
    # include any staged (unpublished) program are filtered out so the
    # shareable page only shows numbers an admin has explicitly signed
    # off on via the Publish action.
    result = lookup_incentive(db, req, public_only=True)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="No active incentive program for this configuration. Contact your INEOS retailer."
        )
    return result


def _preview(db: Session, req: PreviewRequest, public_only: bool) -> PreviewResponse:
    """Run the lookup once per deal type and roll up to the wizard's step-2
    summary. A 'no code' result becomes available=False so the card can grey
    out instead of disappearing."""
    if req.zip_code and not req.state:
        resolved = zip_to_state(req.zip_code)
        if resolved:
            req.state = resolved

    out: dict[str, DealTypePreview] = {}
    for dt in ("cash", "apr", "lease"):
        lr = LookupRequest(
            vin=req.vin,
            model_year=req.model_year,
            body_style=req.body_style,
            trim=req.trim,
            special_edition=req.special_edition,
            msrp=req.msrp,
            finance_type=dt,
            state=req.state,
            zip_code=req.zip_code,
            conquest=False,
            loyalty=False,
        )
        result = lookup_incentive(db, lr, public_only=public_only)
        if result is None:
            out[dt] = DealTypePreview(deal_type=dt, total=0.0, program_count=0, available=False)
        else:
            out[dt] = DealTypePreview(
                deal_type=dt,
                total=result.total_support_amount,
                program_count=len(result.eligible_programs),
                available=True,
            )
    return PreviewResponse(cash=out["cash"], apr=out["apr"], lease=out["lease"])


@router.post("/preview", response_model=PreviewResponse)
def preview_deal_types(
    req: PreviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Authenticated wizard step-2 summary. Includes staged programs."""
    return _preview(db, req, public_only=False)


@router.post("/preview/public", response_model=PreviewResponse)
def public_preview_deal_types(req: PreviewRequest, db: Session = Depends(get_db)):
    """Public wizard step-2 summary. Filters to published programs only,
    matching the production gate on /api/lookup/public."""
    return _preview(db, req, public_only=True)


@router.get("/debug/hub")
def debug_hub(vin: str = "SC6GM1CA6SF026634"):
    """Diagnostic endpoint — reports whether platform_client is configured
    and what the Platform returns for a given VIN. Never echoes the
    service key value. Safe to leave enabled in prod (no secrets, no
    DB writes, no enumeration risk beyond a single-VIN check)."""
    import httpx
    base = platform_client._base_url()
    key_set = bool(platform_client._service_key())
    diag = {
        "is_configured": platform_client.is_configured(),
        "platform_base_url": base or None,
        "platform_service_key_set": key_set,
        "vin_tested": vin,
    }
    if not platform_client.is_configured():
        diag["result"] = "skipped — env vars missing"
        return diag
    try:
        r = httpx.get(
            f"{base}/api/data/vehicle-by-vin/{vin.strip().upper()}",
            headers={"X-Service-Key": platform_client._service_key()},
            timeout=5.0,
        )
        diag["http_status"] = r.status_code
        body = r.text
        diag["response_body_preview"] = body[:500] if body else None
        if r.status_code == 200:
            try:
                diag["mapped"] = platform_client.map_platform_to_incentive_shape(r.json())
            except Exception as e:
                diag["mapping_error"] = repr(e)
        return diag
    except Exception as e:
        diag["network_error"] = repr(e)
        return diag


@router.get("/vin/{vin}")
def vin_lookup(vin: str, db: Session = Depends(get_db)):
    """Resolve a VIN to its vehicle data, in this priority order:

    1. Americas Platform hub (canonical Master File source).
    2. Local Vehicle table (legacy fallback for installs that still
       upload Master File directly to the Incentive App).
    3. VIN-pattern decode (only model year + body style — no MSRP).

    The hub is the source of truth; the local table stays as a
    fallback so deployments without PLATFORM_BASE_URL set still work.
    """
    vin = vin.strip().upper()

    # 1. Hub lookup — short-circuits as soon as it returns data
    hub = platform_client.fetch_vehicle_by_vin(vin)
    if hub:
        return platform_client.map_platform_to_incentive_shape(hub)

    # 2. Local Vehicle table fallback
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

    # 3. VIN-pattern decode fallback (no MSRP available — model year +
    #    body style only). INEOS VINs start with SC6 (Station Wagon) or
    #    SH7 (Quartermaster). 10th char is model year: R=2024, S=2025,
    #    T=2026, V=2027.
    body_style = "station_wagon"
    if vin.startswith("SH7"):
        body_style = "quartermaster"

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
    """Resolve a ZIP code to a state abbreviation, name, and combined
    sales tax rate. tax_rate is the ZIP-precise rate (state + county +
    city + special districts) when the ZIP is in the bundled dataset;
    otherwise falls back to the state baseline. tax_rate_source signals
    which one was used — useful for the UI to label "ZIP-precise" vs
    "state estimate" so the user knows when to override."""
    state = zip_to_state(zip_code)
    if not state:
        raise HTTPException(status_code=404, detail="Could not resolve ZIP code to a state")
    zip_rate = zip_to_combined_tax_rate(zip_code)
    if zip_rate is not None:
        tax_rate = zip_rate
        source = "zip"
    else:
        tax_rate = state_tax_rate(state)
        source = "state"
    return {
        "zip_code": zip_code,
        "state": state,
        "state_name": state_name(state),
        "tax_rate": tax_rate,
        "tax_rate_source": source,
        # 'depreciation' (default) -> tax on (selling - residual)
        # 'full_price' (TX, MD)    -> tax on full selling price like a purchase
        # The calculator uses this to pick the right lease tax base.
        "lease_tax_basis": state_lease_tax_basis(state),
    }


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
    state: str = None,
):
    """Get Santander APR and lease rates for a vehicle configuration.
    Returns rates per term with trim-specific MF and residuals.

    state — when provided (2-letter US state code), state-specific
    rows from the State_INEOS_*Input.xlsx files take precedence over
    the national rate sheet for any (term, tier) combo where the
    state file has a row. National rows still cover terms the state
    sheet is silent on. Without state, national-only rates are
    returned (the historical behavior)."""
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from app.services.santander_rates import (
        get_apr_for_config, get_lease_for_config, get_all_lease_by_trim
    )

    apr_rates = get_apr_for_config(base_dir, model_year, body_style, tier, trim, state)
    lease_rates = get_lease_for_config(base_dir, model_year, body_style, tier, trim, state)
    lease_by_trim = get_all_lease_by_trim(base_dir, model_year, body_style, tier, state)

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

    # Whether the returned rates actually pulled from the state file
    # (vs. all national fallback). The UI uses this to label the
    # rate-source line — "Santander rates (TX)" vs "Santander rates
    # (national)" — so the user knows when state subvention applied.
    state_used = state.upper() if state else None
    has_state_apr = any(r.get("region") == state_used for r in apr_rates) if state_used else False
    has_state_lease = any(r.get("region") == state_used for r in lease_rates) if state_used else False

    return {
        "model_year": model_year,
        "body_style": body_style,
        "trim": trim,
        "tier": tier,
        "state": state_used,
        "has_state_apr": has_state_apr,
        "has_state_lease": has_state_lease,
        "apr": apr_rates,
        "lease": lease_rates,
        "lease_by_trim": lease_by_trim,
        "mileage_degradation": mileage_degradation,
    }


@router.get("/states")
def list_states():
    """Return all US states for dropdown population."""
    return [{"value": s, "label": f"{s} - {STATE_NAMES[s]}"} for s in ALL_STATES]
