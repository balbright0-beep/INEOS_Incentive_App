from pydantic import BaseModel
from datetime import date
from typing import Optional


class ProgramRuleCreate(BaseModel):
    rule_type: str
    operator: str = "in"
    value: dict | list


class ProgramRuleResponse(BaseModel):
    id: str
    rule_type: str
    operator: str
    value: dict | list

    class Config:
        from_attributes = True


class ProgramCreate(BaseModel):
    name: str
    program_type: str
    effective_date: date
    expiration_date: date
    description: Optional[str] = None
    budget_amount: Optional[float] = None
    budget_units: Optional[int] = None
    per_unit_amount: Optional[float] = 0
    stacking_category: Optional[str] = None
    rules: list[ProgramRuleCreate] = []


class ProgramUpdate(BaseModel):
    name: Optional[str] = None
    program_type: Optional[str] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    description: Optional[str] = None
    budget_amount: Optional[float] = None
    budget_units: Optional[int] = None
    per_unit_amount: Optional[float] = None
    stacking_category: Optional[str] = None
    status: Optional[str] = None
    rules: Optional[list[ProgramRuleCreate]] = None


class BudgetResponse(BaseModel):
    id: str
    period: str
    allocated_amount: float
    allocated_units: Optional[int] = None

    class Config:
        from_attributes = True


class ProgramResponse(BaseModel):
    id: str
    name: str
    program_type: str
    status: str
    effective_date: date
    expiration_date: date
    budget_amount: Optional[float] = None
    budget_units: Optional[int] = None
    description: Optional[str] = None
    stacking_category: Optional[str] = None
    per_unit_amount: Optional[float] = 0
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    rules: list[ProgramRuleResponse] = []
    budgets: list[BudgetResponse] = []
    spend_to_date: Optional[float] = 0
    units_to_date: Optional[int] = 0

    class Config:
        from_attributes = True
