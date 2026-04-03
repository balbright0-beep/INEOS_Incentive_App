import uuid
from sqlalchemy import Column, String, Enum, Numeric, DateTime, func
from sqlalchemy.orm import relationship
from app.database import Base

PAY_FILE_STATUSES = ("draft", "submitted", "confirmed")


class PayFile(Base):
    __tablename__ = "pay_files"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    period = Column(String(10), nullable=False)
    generated_date = Column(DateTime, server_default=func.now())
    total_amount = Column(Numeric(14, 2), default=0)
    total_units = Column(Numeric(10, 0), default=0)
    status = Column(Enum(*PAY_FILE_STATUSES, name="pay_file_status"), nullable=False, default="draft")
    file_path = Column(String(500), nullable=True)

    transactions = relationship("DealTransaction", backref="pay_file")
