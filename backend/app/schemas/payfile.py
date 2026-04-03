from pydantic import BaseModel
from typing import Optional


class PayFileResponse(BaseModel):
    id: str
    period: str
    generated_date: Optional[str] = None
    total_amount: float = 0
    total_units: int = 0
    status: str = "draft"
    file_path: Optional[str] = None
    transactions: list = []

    class Config:
        from_attributes = True


class PayFileGenerate(BaseModel):
    period: str  # "2026-03"


class PayFileAdjustment(BaseModel):
    transaction_id: str
    new_amount: Optional[float] = None
    exclude: bool = False
    reason: str = ""
