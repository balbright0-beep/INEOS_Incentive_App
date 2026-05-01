import uuid
from sqlalchemy import Column, String, Enum, Date, Numeric, Text, DateTime, Boolean, func, ForeignKey, JSON, LargeBinary, Integer
from sqlalchemy.orm import relationship
from app.database import Base

PROGRAM_TYPES = (
    "bonus_cash", "customer_cash", "apr_cash", "lease_cash",
    "dealer_cash",  # Dealer-funded incentive — typically stackable with all retail programs
    # VIN-specific rebate (e.g. MSRP rebate on aging stock). Eligibility
    # is gated by VIN being in the program's vin list (ProgramVin); the
    # amount comes from that row, not Program.per_unit_amount. Excluded
    # from the campaign-code matrix because it's per-unit, not per-config.
    "vin_specific",
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


class ProgramBulletin(Base):
    """Admin-uploaded supplemental bulletins attached to a program.

    Distinct from the auto-generated PDF bulletin (services/pdf_generator)
    — that one's regenerated from the program's data on demand and
    written to the OUTPUT_DIR. This model is for arbitrary additional
    docs admins want to ship alongside (Q1 communications, OEM
    updates, dealer FAQ, signed legal addenda, etc.). Bytes live in
    the row so we don't depend on object storage; PDFs are typically
    50KB-2MB and the dataset is bounded (a few per program), so the
    weight is fine."""

    __tablename__ = "program_bulletins"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(300), nullable=False)
    content_type = Column(String(100), nullable=False, default="application/pdf")
    size_bytes = Column(Integer, nullable=False, default=0)
    description = Column(String(500), nullable=True)
    data = Column(LargeBinary, nullable=False)
    uploaded_by = Column(String, nullable=True)  # User.id of the uploader
    uploaded_at = Column(DateTime, server_default=func.now())


class ProgramVin(Base):
    """Per-VIN rebate row for vin_specific programs. One row = one VIN
    eligible for the program, with that VIN's individual rebate amount.
    The amount lives here (not on Program.per_unit_amount) because the
    whole point of vin_specific is that each VIN can have its own
    number — e.g. MSRP rebates on aging stock vary by unit. Excel
    upload writes these in bulk; the existing rows are wiped and
    replaced on each upload so re-uploading the spreadsheet is the
    canonical "update this list" action."""

    __tablename__ = "program_vins"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    vin = Column(String(17), nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
