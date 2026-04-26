import uuid
from sqlalchemy import Column, String, Enum, Date, Numeric, Text, DateTime, Boolean, func, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.database import Base

PROGRAM_TYPES = (
    "bonus_cash", "customer_cash", "apr_cash", "lease_cash",
    "cvp", "demonstrator", "loyalty", "conquest", "tactical", "other"
)
PROGRAM_STATUSES = ("draft", "active", "expired", "cancelled")


class Program(Base):
    __tablename__ = "programs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(300), nullable=False)
    program_type = Column(Enum(*PROGRAM_TYPES, name="program_type"), nullable=False)
    status = Column(Enum(*PROGRAM_STATUSES, name="program_status"), nullable=False, default="draft")
    # Production gate. status='active' alone is "staged" — visible to
    # logged-in admins / RBMs / retailers via the authenticated lookup
    # so they can sanity-check the matrix before exposing it. Setting
    # published=True promotes to production: visible on the public
    # /lookup/ page and any other unauthenticated surface.
    published = Column(Boolean, nullable=False, default=False, server_default="false")
    # Document audience flag. True = customer-facing (PDF bulletin
    # includes the legal disclaimers / advertising disclosures).
    # False = internal-only (e.g. dealer employee programs) — the
    # bulletin still generates so the program is documented, but the
    # customer disclaimer block is skipped because the doc never
    # leaves dealer/admin hands. Independent of published — a
    # program can be internal AND on the public lookup, or private
    # and staged.
    public_facing = Column(Boolean, nullable=False, default=True, server_default="true")
    # Per-program stacking exclusion list — IDs of OTHER programs
    # this one cannot be combined with on the same campaign code.
    # NULL or [] = no per-program exclusions (program-type-level
    # stacking matrix still applies). Symmetric in practice: if
    # A.not_stackable lists B's id, the matrix builder drops one of
    # the pair (lower-amount loses) regardless of whether B
    # reciprocates, so admins only have to set the rule once.
    not_stackable_program_ids = Column(JSON, nullable=True)
    effective_date = Column(Date, nullable=False)
    expiration_date = Column(Date, nullable=False)
    budget_amount = Column(Numeric(14, 2), nullable=True)
    budget_units = Column(Numeric(10, 0), nullable=True)
    description = Column(Text, nullable=True)
    stacking_category = Column(String(100), nullable=True)
    per_unit_amount = Column(Numeric(10, 2), nullable=True, default=0)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    rules = relationship("ProgramRule", back_populates="program", cascade="all, delete-orphan")
    code_layers = relationship("CampaignCodeLayer", back_populates="program")
    budgets = relationship("Budget", back_populates="program", cascade="all, delete-orphan")


RULE_TYPES = (
    "model_year", "body_style", "trim", "finance_type", "channel",
    "region", "dealer", "conquest_brand", "age_days", "mileage_cap",
    "min_service_days", "msrp_range", "special_edition",
    # state-level targeting (e.g. CA-only). The wizard's State Targeting
    # control writes this rule_type, and lookup.py:_program_has_state_
    # restriction reads it. Was missing from the enum, so any program
    # with a state selection failed at INSERT time on Postgres with
    # InvalidTextRepresentation \u2014 surfaced to the UI as a generic
    # "Request failed" toast.
    "state",
)
OPERATORS = ("equals", "not_equals", "in", "not_in", "gte", "lte", "between")


class ProgramRule(Base):
    __tablename__ = "program_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False)
    rule_type = Column(Enum(*RULE_TYPES, name="rule_type"), nullable=False)
    operator = Column(Enum(*OPERATORS, name="rule_operator"), nullable=False, default="in")
    value = Column(JSON, nullable=False)

    program = relationship("Program", back_populates="rules")
