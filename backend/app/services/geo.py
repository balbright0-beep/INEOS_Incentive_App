"""ZIP code to state mapping for geographic program eligibility."""

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
