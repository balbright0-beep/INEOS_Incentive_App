"""Parse Santander APR and Lease input files for rate lookups."""

import os
import glob
from openpyxl import load_workbook


# CPOS code to trim name mapping
CPOS_TO_TRIM = {
    "BASE": "Base",
    "FIELD": "Fieldmaster",
    "BLACK": "Belstaff",
    "TRIAL": "Trialmaster",
    "HIGHL": "Highlands",
}


def _find_input_files(base_dir: str) -> dict:
    """Find the latest Santander APR and Lease input files."""
    files = {"apr": None, "lease": None, "lease_state": None}
    patterns = {
        "apr": "INEOS_APRInput_*.xlsx",
        "lease": "INEOS_LeaseInput_*.xlsx",
        "lease_state": "State_INEOS_LeaseInput_*.xlsx",
    }
    for key, pattern in patterns.items():
        matches = glob.glob(os.path.join(base_dir, pattern))
        if matches:
            files[key] = max(matches, key=os.path.getmtime)
    return files


def _model_code_to_params(model_code: str) -> dict:
    body = "station_wagon" if model_code.startswith("G01") else "quartermaster"
    suffix = model_code[-1] if model_code else "C"
    my = "MY26" if suffix == "D" else "MY25"
    return {"body_style": body, "model_year": my}


def load_apr_rates(base_dir: str) -> list[dict]:
    """Parse the APR input file. Returns list of rate records."""
    files = _find_input_files(base_dir)
    if not files["apr"]:
        return []

    wb = load_workbook(files["apr"], data_only=True, read_only=True)
    ws = wb["Retail"] if "Retail" in wb.sheetnames else wb[wb.sheetnames[0]]
    rates = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        tier = row[2]
        term = row[3]
        model_code = str(row[9] or "")
        cpos = str(row[10] or "").upper()
        rate = row[15]

        if rate is None or str(rate).strip().lower() == "std.":
            continue
        try:
            rate_val = float(rate)
        except (ValueError, TypeError):
            continue

        params = _model_code_to_params(model_code)
        trim = CPOS_TO_TRIM.get(cpos, cpos.title() if cpos else "Base")

        rates.append({
            "tier": int(tier) if tier else 1,
            "term": int(term) if term else 0,
            "model_code": model_code,
            "body_style": params["body_style"],
            "model_year": params["model_year"],
            "trim": trim,
            "apr": rate_val,
        })

    wb.close()
    return rates


def load_lease_rates(base_dir: str) -> list[dict]:
    """Parse the Lease input file. Returns ALL records per trim/term."""
    files = _find_input_files(base_dir)
    if not files["lease"]:
        return []

    wb = load_workbook(files["lease"], data_only=True, read_only=True)
    ws = wb["Lease"] if "Lease" in wb.sheetnames else wb[wb.sheetnames[0]]
    rates = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        tier = row[2]
        term = row[3]
        model_code = str(row[8] or "")
        cpos = str(row[9] or "").upper()
        mf = row[14]
        acq_fee = row[15]
        residual = row[19]  # Published INEOS Residual

        mf_val = None
        if mf is not None and str(mf).strip().lower() != "std.":
            try:
                mf_val = float(mf)
            except (ValueError, TypeError):
                pass

        res_val = None
        if residual is not None:
            try:
                res_val = float(str(residual).replace("%", ""))
            except (ValueError, TypeError):
                pass

        params = _model_code_to_params(model_code)
        trim = CPOS_TO_TRIM.get(cpos, cpos.title() if cpos else "Base")

        rates.append({
            "tier": int(tier) if tier else 1,
            "term": int(term) if term else 0,
            "model_code": model_code,
            "body_style": params["body_style"],
            "model_year": params["model_year"],
            "trim": trim,
            "money_factor": mf_val,
            "money_factor_display": str(mf) if mf else "Std.",
            "residual_pct": res_val,
            "acq_fee": float(acq_fee) if acq_fee else 895,
        })

    wb.close()
    return rates


def get_apr_for_config(base_dir: str, model_year: str, body_style: str,
                       tier: int = 1, trim: str = None) -> list[dict]:
    """Get APR rates. If trim specified, filter to that trim. Deduplicated by term."""
    all_rates = load_apr_rates(base_dir)
    matching = [
        r for r in all_rates
        if r["model_year"] == model_year
        and r["body_style"] == body_style
        and r["tier"] == tier
    ]
    if trim:
        trim_match = [r for r in matching if r["trim"].lower() == trim.lower()]
        if trim_match:
            matching = trim_match

    by_term = {}
    for r in matching:
        t = r["term"]
        if t not in by_term or r["apr"] < by_term[t]["apr"]:
            by_term[t] = r
    return sorted(by_term.values(), key=lambda r: r["term"])


def get_lease_for_config(base_dir: str, model_year: str, body_style: str,
                         tier: int = 1, trim: str = None) -> list[dict]:
    """Get lease rates. If trim specified, filter to that trim. Deduplicated by term."""
    all_rates = load_lease_rates(base_dir)
    matching = [
        r for r in all_rates
        if r["model_year"] == model_year
        and r["body_style"] == body_style
        and r["tier"] == tier
    ]
    if trim:
        trim_match = [r for r in matching if r["trim"].lower() == trim.lower()]
        if trim_match:
            matching = trim_match

    by_term = {}
    for r in matching:
        t = r["term"]
        if t not in by_term:
            by_term[t] = r
        elif r["money_factor"] is not None and (
            by_term[t]["money_factor"] is None or r["money_factor"] < by_term[t]["money_factor"]
        ):
            by_term[t] = r
    return sorted(by_term.values(), key=lambda r: r["term"])


def get_all_lease_by_trim(base_dir: str, model_year: str, body_style: str,
                          tier: int = 1) -> dict[str, list[dict]]:
    """Get lease rates grouped by trim for comparison display."""
    all_rates = load_lease_rates(base_dir)
    matching = [
        r for r in all_rates
        if r["model_year"] == model_year
        and r["body_style"] == body_style
        and r["tier"] == tier
    ]
    by_trim = {}
    for r in matching:
        trim = r["trim"]
        by_trim.setdefault(trim, {})
        t = r["term"]
        if t not in by_trim[trim]:
            by_trim[trim][t] = r
        elif r["money_factor"] is not None and (
            by_trim[trim][t]["money_factor"] is None or r["money_factor"] < by_trim[trim][t]["money_factor"]
        ):
            by_trim[trim][t] = r

    result = {}
    for trim, terms in by_trim.items():
        result[trim] = sorted(terms.values(), key=lambda r: r["term"])
    return result
