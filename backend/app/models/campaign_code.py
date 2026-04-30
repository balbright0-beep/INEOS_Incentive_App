import uuid
from sqlalchemy import Column, String, Enum, Boolean, Date, Numeric, DateTime, func, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

# Arcane Works (G13C SVO/Detour) gets its own body code rather than
# riding on station_wagon + special_edition='arcane_works_detour'.
# That older modeling collapsed Arcane into the SW rate sheet and
# campaign-code matrix, which broke once Arcane started having
# distinct rate rows + a need for cleanly separable campaign codes.
BODY_STYLES = ("station_wagon", "quartermaster", "arcane_works")
DEAL_TYPES = ("cash", "apr", "lease", "cvp", "demo")


class CampaignCode(Base):
    __tablename__ = "campaign_codes"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Bumped 6 → 10 → 12. The 10-bump lets APR/Lease codes carry a
    # model-year digit (USASWS vs USASWT). The 12-bump makes room
    # for special-edition codes that need US + sp[3] + body[2] +
    # my[1] + dt[1] + flags[2] = 12 chars (e.g. USARDSWTCLC for an
    # MY26 SW Arcane Cash + Loyalty + Conquest combo). Existing
    # shorter codes stay valid.
    code = Column(String(12), unique=True, nullable=False, index=True)
    label = Column(String(300), nullable=True)
    support_amount = Column(Numeric(10, 2), nullable=False, default=0)
    model_year = Column(String(10), nullable=True)
    body_style = Column(Enum(*BODY_STYLES, name="body_style_enum"), nullable=True)
    trim = Column(String(100), nullable=True)
    deal_type = Column(Enum(*DEAL_TYPES, name="deal_type_enum"), nullable=True)
    loyalty_flag = Column(Boolean, default=False)
    conquest_flag = Column(Boolean, default=False)
    special_flag = Column(String(100), nullable=True)
    active = Column(Boolean, default=True)
    effective_date = Column(Date, nullable=True)
    expiration_date = Column(Date, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    layers = relationship("CampaignCodeLayer", back_populates="campaign_code", cascade="all, delete-orphan")


class CampaignCodeLayer(Base):
    __tablename__ = "campaign_code_layers"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_code_id = Column(String, ForeignKey("campaign_codes.id", ondelete="CASCADE"), nullable=False)
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False)
    layer_amount = Column(Numeric(10, 2), nullable=False, default=0)

    campaign_code = relationship("CampaignCode", back_populates="layers")
    program = relationship("Program", back_populates="code_layers")
