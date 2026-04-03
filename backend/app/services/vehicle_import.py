"""Master File vehicle inventory import service."""

import io
import re
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.vehicle import Vehicle

# Try to import xlsb support
try:
    import msoffcrypto
    from pyxlsb import open_workbook as open_xlsb
    HAS_XLSB = True
except ImportError:
    HAS_XLSB = False

MASTER_FILE_PASSWORD = "INEOS26"

# Column index mapping for the Export sheet
COL = {
    "dealer_name": 0,
    "ship_to": 1,
    "sales_order": 3,
    "material_desc": 7,
    "vin": 8,
    "stock_category": 9,
    "status_text": 13,
    "msrp": 18,
    "trim": 19,
    "exterior_color": 21,
    "interior_color": 22,
    "handover_date": 51,
    "cvp": 62,
    "demo": 63,
    "campaign_code": 75,
}


def _parse_material(material_desc: str) -> tuple[str, str, str | None]:
    """Parse 'Station Wagon 5-Seat MY25' into (body_style, model_year, special_edition)."""
    if not material_desc:
        return ("station_wagon", "MY25", None)

    body_style = "station_wagon"
    if "quartermaster" in material_desc.lower():
        body_style = "quartermaster"

    model_year = "MY25"
    my_match = re.search(r'MY(\d{2})', material_desc)
    if my_match:
        model_year = f"MY{my_match.group(1)}"

    special = None
    if "arcane" in material_desc.lower():
        special = "arcane_works_detour"
    elif "iceland" in material_desc.lower():
        special = "iceland_tactical"

    return (body_style, model_year, special)


def _parse_trim(trim_str: str) -> str:
    """Normalize trim level names to match product catalog."""
    if not trim_str:
        return "Base"
    t = trim_str.strip().upper()
    # Substring-based matching for inventory variations
    if "FIELDMASTER" in t:
        return "Fieldmaster"
    if "TRIALMASTER" in t and "X" not in t:
        return "Trialmaster"
    if "TRIALMASTER" in t and "X" in t:
        return "Trialmaster"
    if "BELSTAFF" in t or "BLACK EDITION" in t:
        return "Belstaff"
    if "HIGHLANDS" in t:
        return "Highlands"
    if "ARCANE" in t:
        return "Arcane Works Detour"
    if "BASE" in t:
        return "Base"
    return trim_str.strip().title()


def _parse_status(stock_cat: str, status_text: str, cvp: str, demo: str) -> str:
    """Determine vehicle status."""
    if cvp and str(cvp).lower() in ("yes", "y", "true"):
        return "CVP"
    if demo and str(demo).lower() in ("yes", "y", "true"):
        return "Demo"
    if stock_cat:
        cat = str(stock_cat).upper()
        if "SOLD" in cat or "RETAIL" in cat or "LIVE CUSTOMER" in cat:
            return "Sold"
        if "TRANSIT" in cat:
            return "In Transit"
        if "STOCK" in cat:
            return "In Stock"
    if status_text:
        txt = str(status_text).lower()
        if "sold" in txt or "retail" in txt:
            return "Sold"
        if "stock" in txt:
            return "In Stock"
    return "Unknown"


def _excel_date(val) -> datetime | None:
    """Convert Excel serial date to Python date."""
    if not val:
        return None
    try:
        num = float(val)
        if num > 40000:  # Reasonable Excel date range
            return (datetime(1899, 12, 30) + timedelta(days=int(num))).date()
    except (ValueError, TypeError):
        pass
    return None


def _cell_val(row, col_idx):
    """Safely get a cell value from a pyxlsb row."""
    if col_idx < len(row):
        return row[col_idx].v
    return None


def import_master_file(db: Session, file_bytes: bytes, filename: str) -> dict:
    """Import vehicle inventory from a Master File (.xlsb or .xlsx)."""
    results = {"total_rows": 0, "imported": 0, "updated": 0, "skipped": 0, "errors": 0, "details": []}

    if not HAS_XLSB:
        results["errors"] = 1
        results["details"].append("pyxlsb and msoffcrypto packages required for .xlsb files")
        return results

    try:
        # Decrypt if encrypted
        buf = io.BytesIO(file_bytes)
        try:
            ms = msoffcrypto.OfficeFile(buf)
            if ms.is_encrypted():
                decrypted = io.BytesIO()
                ms.load_key(password=MASTER_FILE_PASSWORD)
                ms.decrypt(decrypted)
                decrypted.seek(0)
                buf = decrypted
        except Exception:
            buf.seek(0)  # Not encrypted, use as-is

        with open_xlsb(buf) as wb:
            if "Export" not in wb.sheets:
                results["errors"] = 1
                results["details"].append(f"'Export' sheet not found. Available: {wb.sheets[:10]}")
                return results

            with wb.get_sheet("Export") as ws:
                header_found = False
                for row_num, row in enumerate(ws.rows()):
                    # Skip until we find the header row
                    if not header_found:
                        vin_col = _cell_val(row, COL["vin"])
                        if vin_col and "VIN" in str(vin_col).upper():
                            header_found = True
                        continue

                    results["total_rows"] += 1
                    try:
                        vin = str(_cell_val(row, COL["vin"]) or "").strip()
                        if not vin or len(vin) < 10:
                            results["skipped"] += 1
                            continue

                        material = str(_cell_val(row, COL["material_desc"]) or "")
                        body_style, model_year, special = _parse_material(material)
                        trim = _parse_trim(str(_cell_val(row, COL["trim"]) or ""))

                        ship_to = _cell_val(row, COL["ship_to"])
                        ship_to = str(int(float(ship_to))) if ship_to else None

                        msrp_val = _cell_val(row, COL["msrp"])
                        msrp = Decimal(str(msrp_val)) if msrp_val else None

                        dealer_name = str(_cell_val(row, COL["dealer_name"]) or "").strip()
                        stock_cat = str(_cell_val(row, COL["stock_category"]) or "")
                        status_text = str(_cell_val(row, COL["status_text"]) or "")
                        cvp_flag = str(_cell_val(row, COL["cvp"]) or "")
                        demo_flag = str(_cell_val(row, COL["demo"]) or "")
                        status = _parse_status(stock_cat, status_text, cvp_flag, demo_flag)

                        ext_color = str(_cell_val(row, COL["exterior_color"]) or "").strip() or None
                        int_color = str(_cell_val(row, COL["interior_color"]) or "").strip() or None
                        handover = _excel_date(_cell_val(row, COL["handover_date"]))

                        # Upsert: update if VIN exists, insert if new
                        existing = db.query(Vehicle).filter(Vehicle.vin == vin).first()
                        if existing:
                            existing.model_year = model_year
                            existing.body_style = body_style
                            existing.trim = trim
                            existing.special_edition = special
                            existing.material = material
                            existing.msrp = msrp
                            existing.dealer_ship_to = ship_to
                            existing.dealer_name = dealer_name
                            existing.status = status
                            existing.color_exterior = ext_color
                            existing.color_interior = int_color
                            existing.retail_date = handover
                            results["updated"] += 1
                        else:
                            db.add(Vehicle(
                                vin=vin,
                                model_year=model_year,
                                body_style=body_style,
                                trim=trim,
                                special_edition=special,
                                material=material,
                                msrp=msrp,
                                dealer_ship_to=ship_to,
                                dealer_name=dealer_name,
                                status=status,
                                color_exterior=ext_color,
                                color_interior=int_color,
                                retail_date=handover,
                            ))
                            results["imported"] += 1

                    except Exception as e:
                        results["errors"] += 1
                        if results["errors"] <= 10:
                            results["details"].append(f"Row {row_num}: {str(e)[:100]}")

        db.commit()
    except Exception as e:
        results["errors"] += 1
        results["details"].append(f"File error: {str(e)[:200]}")

    return results


def import_master_file_from_path(db: Session, file_path: str) -> dict:
    """Import master file from a filesystem path."""
    with open(file_path, "rb") as f:
        return import_master_file(db, f.read(), file_path)
