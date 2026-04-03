from pydantic import BaseModel
from typing import Optional


class SpendSummary(BaseModel):
    total_spend_mtd: float = 0
    total_budget: float = 0
    utilization_pct: float = 0
    total_units_mtd: int = 0
    avg_incentive_per_unit: float = 0
    projected_month_end: float = 0


class SpendByProgram(BaseModel):
    program_name: str
    program_type: str
    spend: float
    units: int
    budget: float


class SpendByRegion(BaseModel):
    region: str
    spend: float
    units: int


class SpendByDealer(BaseModel):
    dealer_name: str
    ship_to_code: str
    region: str
    spend: float
    units: int
    avg_per_unit: float
