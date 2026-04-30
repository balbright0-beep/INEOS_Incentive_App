"""Service-to-service client for the INEOS Americas Platform hub.

The Platform is the canonical source of vehicle inventory data
(populated from the Master File .xlsb). Other Hub-connected apps
(this Incentive App, the Fleet App) reach into it instead of keeping
their own copies. Auth is a shared secret in PLATFORM_SERVICE_KEY,
set as an env var on both ends.
"""

import os
import httpx


def _base_url() -> str:
    return os.environ.get("PLATFORM_BASE_URL", "").rstrip("/")


def _service_key() -> str:
    return os.environ.get("PLATFORM_SERVICE_KEY", "").strip()


def is_configured() -> bool:
    """True when both env vars are set so the hub call can be attempted."""
    return bool(_base_url() and _service_key())


def fetch_vehicle_by_vin(vin: str, timeout: float = 5.0) -> dict | None:
    """Fetch a vehicle's full record from the Americas Platform hub.

    Returns None on any failure mode — hub unreachable, hub returns
    non-200, service auth not configured, network timeout. Callers
    should fall back to the local Vehicle table and then VIN-pattern
    decode in that order.
    """
    if not is_configured():
        return None
    base = _base_url()
    key = _service_key()
    try:
        r = httpx.get(
            f"{base}/api/data/vehicle-by-vin/{vin.strip().upper()}",
            headers={"X-Service-Key": key},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


# --- Field mapping: Platform shape -> Incentive App shape ---
#
# The Platform stores body as "SW" / "QM" / "SVO" (Master File format),
# colors as ext_color / int_color, dealer as a single dealer field. The
# Incentive App's lookup response uses body_style ("station_wagon" /
# "quartermaster"), color_exterior / color_interior, dealer_name. This
# normalizer keeps the hub call transparent to callers — they get back
# the same shape that the local Vehicle table query returns.

def _normalize_body(body: str | None, trim: str | None = None) -> str:
    """Map the Platform body code to the Incentive App's body_style enum.
    Arcane Works (G13C / SVO) is now its OWN body code rather than
    riding on station_wagon — that change is what lets Arcane have
    distinct rate sheets, campaign codes, and program targeting.
    Detection: the Platform body field comes back as SVO for Arcane,
    or the trim string contains 'ARCANE' as a fallback."""
    if not body:
        # No body code? Last-resort check on the trim string.
        if trim and "ARCANE" in trim.upper():
            return "arcane_works"
        return "station_wagon"
    b = body.upper().strip()
    if b == "QM":
        return "quartermaster"
    if b == "SVO" or (trim and "ARCANE" in trim.upper()):
        return "arcane_works"
    return "station_wagon"


def _normalize_model_year(my: str | None) -> str | None:
    """Master File stores model year as 'MY25' or sometimes '2025' / '25'.
    The Incentive App expects the 'MY25' form."""
    if not my:
        return None
    s = str(my).strip().upper()
    if s.startswith("MY"):
        return s
    if s.isdigit():
        if len(s) == 4:
            return f"MY{s[2:]}"
        if len(s) == 2:
            return f"MY{s}"
    return s


def _detect_special_edition(trim: str | None) -> str | None:
    """The Platform doesn't store a separate special_edition field —
    it's encoded in the trim or material desc. Iceland Tactical stays
    a special edition because it's still a SW/QM trim package.
    Arcane Works is no longer reported here because it's now a
    first-class body_style instead of a trim/special edition."""
    if not trim:
        return None
    t = trim.upper()
    if "ICELAND" in t:
        return "iceland_tactical"
    return None


def _normalize_trim(trim: str | None) -> str | None:
    """Map free-form trim text to the Incentive App's catalog values
    so the campaign-code lookup matches. Mirrors vehicle_import._parse_trim."""
    if not trim:
        return None
    t = trim.strip().upper()
    if "FIELDMASTER" in t:
        return "Fieldmaster"
    if "TRIALMASTER" in t:
        return "Trialmaster"
    if "BELSTAFF" in t or "BLACK EDITION" in t:
        return "Belstaff"
    if "HIGHLANDS" in t:
        return "Highlands"
    if "ARCANE" in t:
        return "Arcane Works Detour"
    if "BASE" in t:
        return "Base"
    return trim.strip().title()


def map_platform_to_incentive_shape(p: dict) -> dict:
    """Translate a Platform /vehicle-by-vin response into the response
    shape the Incentive App's /api/lookup/vin/{vin} returns. Keeps
    callers (the public Incentive Finder, the SPA dealer lookup)
    unchanged regardless of where the data came from."""
    return {
        "vin": p.get("vin"),
        "model_year": _normalize_model_year(p.get("model_year")),
        "body_style": _normalize_body(p.get("body"), p.get("trim")),
        "trim": _normalize_trim(p.get("trim")),
        "special_edition": _detect_special_edition(p.get("trim")),
        "msrp": float(p["msrp"]) if p.get("msrp") is not None else None,
        "material": None,  # Platform doesn't carry the SAP material code separately
        "color_exterior": p.get("ext_color"),
        "color_interior": p.get("int_color"),
        "dealer_name": p.get("dealer"),
        "dealer_ship_to": None,  # Platform stores dealer name only
        "status": p.get("status"),
        "source": "hub",  # distinct from "inventory" (local) and "vin_pattern" (decode)
    }
