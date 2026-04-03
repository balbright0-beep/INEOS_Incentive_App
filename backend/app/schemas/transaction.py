from pydantic import BaseModel
from typing import Optional
from datetime import date


class TransactionResponse(BaseModel):
    id: str
    vin: str
    campaign_code: Optional[str] = None
    dealer_ship_to: Optional[str] = None
    dealer_name: Optional[str] = None
    sales_order: Optional[str] = None
    retail_date: Optional[date] = None
    channel: Optional[str] = None
    material: Optional[str] = None
    trim: Optional[str] = None
    msrp: Optional[float] = None
    support_amount: Optional[float] = None
    payment_status: str = "pending"
    pay_file_id: Optional[str] = None
    import_date: Optional[str] = None
    source_file: Optional[str] = None
    anomaly_flag: Optional[str] = None
    anomaly_resolved: str = "N"

    class Config:
        from_attributes = True


class TransactionUpdate(BaseModel):
    support_amount: Optional[float] = None
    payment_status: Optional[str] = None
    anomaly_resolved: Optional[str] = None


class ImportResult(BaseModel):
    total_rows: int
    imported: int
    duplicates: int
    errors: int
    anomalies: int
    details: list[str] = []
