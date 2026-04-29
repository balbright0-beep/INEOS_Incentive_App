"""ZIP code to state mapping for geographic program eligibility."""

import csv
import os

# ZIP code prefix ranges to state mapping
# Each entry is (start_prefix, end_prefix, state_abbrev)
ZIP_RANGES = [
    ("005", "009", "NY"), ("010", "027", "MA"), ("028", "029", "RI"),
    ("030", "038", "NH"), ("039", "049", "ME"), ("050", "059", "VT"),
    ("060", "069", "CT"), ("070", "089", "NJ"), ("090", "099", "AE"),
    ("100", "149", "NY"), ("150", "196", "PA"), ("197", "199", "DE"),
    ("200", "205", "DC"), ("206", "219", "MD"), ("220", "246", "VA"),
    ("247", "268", "WV"), ("270", "289", "NC"), ("290", "299", "SC"),
    ("300", "319", "GA"), ("320", "339", "FL"), ("340", "349", "AA"),
    ("350", "369", "AL"), ("370", "385", "TN"), ("386", "397", "MS"),
    ("400", "418", "KY"), ("420", "427", "KY"), ("430", "458", "OH"),
    ("460", "479", "IN"), ("480", "499", "MI"), ("500", "528", "IA"),
    ("530", "549", "WI"), ("550", "567", "MN"), ("570", "577", "SD"),
    ("580", "588", "ND"), ("590", "599", "MT"), ("600", "629", "IL"),
    ("630", "658", "MO"), ("660", "679", "KS"), ("680", "693", "NE"),
    ("700", "714", "LA"), ("716", "729", "AR"), ("730", "749", "OK"),
    ("750", "799", "TX"), ("800", "816", "CO"), ("820", "831", "WY"),
    ("832", "838", "ID"), ("840", "847", "UT"), ("850", "865", "AZ"),
    ("870", "884", "NM"), ("889", "898", "NV"), ("900", "935", "CA"),
    ("936", "966", "CA"), ("967", "968", "HI"), ("970", "979", "OR"),
    ("980", "994", "WA"), ("995", "999", "AK"),
]

# Full state name to abbreviation
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# All US states for dropdowns
ALL_STATES = sorted(STATE_NAMES.keys())


# State sales tax baseline (general state rate, percent). Used as the
# default "tax rate" the payment calculator pre-fills from a customer's
# ZIP. Local additions (county / city), motor-vehicle-specific rates,
# and trade-in deduction rules vary too much to encode here — the user
# can override the rate per-deal in the calculator. Source: state DOR
# general sales tax rates as of 2026; AK/DE/MT/NH/OR have no state
# sales tax (vehicle excise / registration fees apply but aren't a
# % of price). Numbers are best-effort defaults, not legal advice.
STATE_TAX_RATES = {
    "AL": 4.0,    "AK": 0.0,    "AZ": 5.6,    "AR": 6.5,
    "CA": 7.25,   "CO": 2.9,    "CT": 6.35,   "DE": 0.0,
    "DC": 6.0,    "FL": 6.0,    "GA": 4.0,    "HI": 4.0,
    "ID": 6.0,    "IL": 6.25,   "IN": 7.0,    "IA": 6.0,
    "KS": 6.5,    "KY": 6.0,    "LA": 4.45,   "ME": 5.5,
    "MD": 6.0,    "MA": 6.25,   "MI": 6.0,    "MN": 6.875,
    "MS": 7.0,    "MO": 4.225,  "MT": 0.0,    "NE": 5.5,
    "NV": 6.85,   "NH": 0.0,    "NJ": 6.625,  "NM": 5.125,
    "NY": 4.0,    "NC": 4.75,   "ND": 5.0,    "OH": 5.75,
    "OK": 4.5,    "OR": 0.0,    "PA": 6.0,    "RI": 7.0,
    "SC": 6.0,    "SD": 4.0,    "TN": 7.0,    "TX": 6.25,
    "UT": 6.1,    "VT": 6.0,    "VA": 4.15,   "WA": 6.5,
    "WV": 6.0,    "WI": 5.0,    "WY": 4.0,
}


def state_tax_rate(state: str | None) -> float:
    """Return the default sales tax rate (percent) for a state. Falls
    back to 0.0 for unknown states / no-sales-tax states. Used as a
    fallback when zip_to_combined_tax_rate doesn't have an entry for
    the customer's ZIP. The calculator UI lets the user override
    either source so locality and motor-vehicle-specific rules can be
    applied per-deal."""
    if not state:
        return 0.0
    return float(STATE_TAX_RATES.get(state.upper(), 0.0))


# States where the full sales price (or total of all payments + residual)
# is the lease tax base, instead of the depreciation portion. Most states
# use depreciation-basis taxation (either upfront on the cap reduction or
# amortized into monthly payments — both math out the same). The handful
# that tax the full contract value are an exception worth encoding so the
# calculator picks the right basis automatically.
#
# Currently encoded:
#   • TX — Motor vehicle tax 6.25% on total consideration
#   • MD — Tax on total of all lease payments + residual (≈ full price)
#
# Add to this set as more states are confirmed. IL was full-price pre-2015
# but switched to monthly-payment tax (= depreciation-basis); it stays in
# the depreciation default. State rules change — re-verify annually.
LEASE_FULL_PRICE_STATES = {"TX", "MD"}


def state_lease_tax_basis(state: str | None) -> str:
    """Return 'full_price' or 'depreciation' indicating how a state taxes
    vehicle leases. Used by the calculator to pick the right tax base —
    full selling price like a purchase, or just the (selling - residual)
    depreciation portion. Defaults to 'depreciation' since that's the
    majority rule and the conservative choice."""
    if state and state.upper() in LEASE_FULL_PRICE_STATES:
        return "full_price"
    return "depreciation"


# ZIP-to-combined-rate cache. The bundled CSV is read once on first
# call and held in memory (~1.1 MB / 39K rows) so subsequent lookups
# are O(1) dict access. None means "not loaded yet"; an empty dict
# means "load attempted but the file was missing or unreadable" so we
# don't repeatedly retry. See backend/data/README.md for source +
# refresh instructions.
_ZIP_TAX_CACHE: dict[str, float] | None = None


def _zip_tax_csv_path() -> str:
    here = os.path.dirname(__file__)
    # geo.py lives at backend/app/services/geo.py; the data lives at
    # backend/data/zip_tax_rates.csv (three levels up + back down).
    return os.path.normpath(os.path.join(here, "..", "..", "data", "zip_tax_rates.csv"))


def _load_zip_tax_rates() -> dict[str, float]:
    global _ZIP_TAX_CACHE
    if _ZIP_TAX_CACHE is not None:
        return _ZIP_TAX_CACHE
    out: dict[str, float] = {}
    path = _zip_tax_csv_path()
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                zip_code = (row.get("Postcode / ZIP") or "").strip()
                rate_str = (row.get("Rate %") or "").strip()
                if not zip_code or not rate_str:
                    continue
                try:
                    out[zip_code] = float(rate_str)
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    _ZIP_TAX_CACHE = out
    return out


def zip_to_combined_tax_rate(zip_code: str | None) -> float | None:
    """Return the ZIP-precise combined sales tax rate (percent) covering
    state + county + city + special districts, or None when the ZIP isn't
    in the bundled dataset. Callers should fall back to state_tax_rate
    on None so we still return a reasonable estimate for ZIPs the
    dataset misses."""
    if not zip_code:
        return None
    clean = zip_code.strip().replace("-", "")[:5]
    if len(clean) != 5 or not clean.isdigit():
        return None
    return _load_zip_tax_rates().get(clean)


def zip_to_state(zip_code: str) -> str | None:
    """Convert a ZIP code to a 2-letter state abbreviation."""
    if not zip_code:
        return None
    clean = zip_code.strip().replace("-", "")[:5]
    if len(clean) < 3 or not clean.isdigit():
        return None
    prefix = clean[:3]
    for start, end, state in ZIP_RANGES:
        if start <= prefix <= end:
            return state
    return None


def state_name(abbrev: str) -> str:
    """Get full state name from abbreviation."""
    return STATE_NAMES.get(abbrev.upper(), abbrev) if abbrev else ""
