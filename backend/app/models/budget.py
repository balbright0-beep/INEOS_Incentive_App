import uuid
from sqlalchemy import Column, String, Enum, Numeric, DateTime, func, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.database import Base


class Budget(Base):
    __tablename__ = "budgets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False)
    period = Column(String(10), nullable=False)
    allocated_amount = Column(Numeric(14, 2), default=0)
    allocated_units = Column(Numeric(10, 0), nullable=True)

    program = relationship("Program", back_populates="budgets")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String, nullable=False)
    action = Column(String(50), nullable=False)
    user_id = Column(String, nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class StackingRule(Base):
    __tablename__ = "stacking_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    deal_type = Column(String(20), nullable=False)
    program_type = Column(String(50), nullable=False)
    allowed = Column(String(1), nullable=False, default="Y")
