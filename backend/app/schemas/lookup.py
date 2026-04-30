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


class EligibleProgram(BaseModel):
    """One pickable program in the retailer-facing chooser. The Find
    tab presents these as toggles so the retailer can include or skip
    any program before generating the final total. `auto_selected`
    indicates whether this program is in the matrix code's default
    layer set (i.e. would be applied if the retailer accepts the
    auto-stack); `conflicts_with` lists program ids that can't co-
    exist with this one — the UI uses both to enable smart toggles."""
    program_id: str
    program_name: str
    program_type: str
    amount: float
    auto_selected: bool
    conflicts_with: list[str] = []


class LookupResponse(BaseModel):
    code: str
    total_support_amount: float
    label: str
    layers: list[IncentiveLayer]
    not_applicable: list[dict] = []
    eligible_programs: list[EligibleProgram] = []
    model_year: str
    body_style: str
    deal_type: str
    loyalty: bool
    conquest: bool


class DealTypePreview(BaseModel):
    """One deal-type summary for the wizard's step 2 cards. `available`
    is False when no campaign code matches OR when the deal type lacks
    Santander rates for the vehicle (e.g. Arcane Works has APR rows
    but no lease rows). `unavailable_reason` is shown on the greyed
    card so the user understands why the option is disabled."""
    deal_type: str
    total: float
    program_count: int
    available: bool
    unavailable_reason: Optional[str] = None  # populated when available=False


class PreviewRequest(BaseModel):
    vin: Optional[str] = None
    model_year: str
    body_style: str
    trim: Optional[str] = None
    special_edition: Optional[str] = None
    msrp: Optional[float] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None


class PreviewResponse(BaseModel):
    cash: DealTypePreview
    apr: DealTypePreview
    lease: DealTypePreview
