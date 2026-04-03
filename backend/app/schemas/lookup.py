from pydantic import BaseModel
from typing import Optional


class LookupRequest(BaseModel):
    vin: Optional[str] = None
    model_year: str
    body_style: str  # "station_wagon" or "quartermaster"
    trim: Optional[str] = None
    special_edition: Optional[str] = None
    msrp: Optional[float] = None
    finance_type: str  # "cash", "apr", "lease"
    lender: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    conquest: bool = False
    conquest_brand: Optional[str] = None
    loyalty: bool = False
    loyalty_vin: Optional[str] = None
    dealer_id: Optional[str] = None


class IncentiveLayer(BaseModel):
    program_name: str
    program_type: str
    amount: float


class LookupResponse(BaseModel):
    code: str
    total_support_amount: float
    label: str
    layers: list[IncentiveLayer]
    not_applicable: list[dict] = []
    model_year: str
    body_style: str
    deal_type: str
    loyalty: bool
    conquest: bool
