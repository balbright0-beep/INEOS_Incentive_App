from pydantic import BaseModel
from typing import Optional
from datetime import date


class CodeLayerResponse(BaseModel):
    id: str
    program_id: str
    program_name: Optional[str] = None
    layer_amount: float

    class Config:
        from_attributes = True


class CampaignCodeResponse(BaseModel):
    id: str
    code: str
    label: Optional[str] = None
    support_amount: float
    model_year: Optional[str] = None
    body_style: Optional[str] = None
    trim: Optional[str] = None
    deal_type: Optional[str] = None
    loyalty_flag: bool = False
    conquest_flag: bool = False
    special_flag: Optional[str] = None
    active: bool = True
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    layers: list[CodeLayerResponse] = []

    class Config:
        from_attributes = True


class CampaignCodeUpdate(BaseModel):
    code: Optional[str] = None
    label: Optional[str] = None
    support_amount: Optional[float] = None
    active: Optional[bool] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None


class MatrixDiffItem(BaseModel):
    code: str
    label: str
    model_year: str
    body_style: str
    deal_type: str
    loyalty_flag: bool
    conquest_flag: bool
    special_flag: Optional[str] = None
    current_amount: Optional[float] = None
    new_amount: float
    change_type: str  # "new", "changed", "unchanged", "retiring"
    layers: list[dict] = []
