"""Stacking rules engine: determines which program types apply to which deal types."""

from sqlalchemy.orm import Session
from app.models.budget import StackingRule

# Default stacking matrix
DEFAULT_STACKING = {
    "cash": ["bonus_cash", "customer_cash", "loyalty", "conquest", "tactical"],
    "apr": ["bonus_cash", "apr_cash", "loyalty", "conquest", "tactical"],
    "lease": ["bonus_cash", "lease_cash", "loyalty", "conquest", "tactical"],
    "cvp": ["bonus_cash", "cvp"],
    "demo": ["bonus_cash", "demonstrator"],
}


def get_stacking_matrix(db: Session) -> dict[str, list[str]]:
    rules = db.query(StackingRule).all()
    if not rules:
        return DEFAULT_STACKING
    matrix: dict[str, list[str]] = {}
    for rule in rules:
        if rule.allowed == "Y":
            matrix.setdefault(rule.deal_type, []).append(rule.program_type)
    return matrix if matrix else DEFAULT_STACKING


def is_program_applicable(deal_type: str, program_type: str, matrix: dict) -> bool:
    allowed = matrix.get(deal_type, [])
    return program_type in allowed


def seed_default_stacking(db: Session):
    existing = db.query(StackingRule).count()
    if existing > 0:
        return
    for deal_type, program_types in DEFAULT_STACKING.items():
        all_types = [
            "bonus_cash", "customer_cash", "apr_cash", "lease_cash",
            "cvp", "demonstrator", "loyalty", "conquest", "tactical", "other"
        ]
        for pt in all_types:
            db.add(StackingRule(
                deal_type=deal_type,
                program_type=pt,
                allowed="Y" if pt in program_types else "N"
            ))
    db.commit()
