import uuid
from sqlalchemy import Column, String, Enum, Numeric, Date, DateTime, func, ForeignKey
from app.database import Base

PAYMENT_STATUSES = ("pending", "submitted", "paid", "rejected", "reversed")


class DealTransaction(Base):
    __tablename__ = "deal_transactions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vin = Column(String(17), nullable=False, index=True)
    campaign_code = Column(String(10), nullable=True)
    dealer_ship_to = Column(String(20), nullable=True)
    dealer_name = Column(String(300), nullable=True)
    sales_order = Column(String(50), nullable=True)
    retail_date = Column(Date, nullable=True)
    channel = Column(String(10), nullable=True)
    material = Column(String(50), nullable=True)
    trim = Column(String(100), nullable=True)
    msrp = Column(Numeric(10, 2), nullable=True)
    support_amount = Column(Numeric(10, 2), nullable=True)
    payment_status = Column(Enum(*PAYMENT_STATUSES, name="payment_status"), nullable=False, default="pending")
    pay_file_id = Column(String, ForeignKey("pay_files.id"), nullable=True)
    import_date = Column(DateTime, server_default=func.now())
    source_file = Column(String(500), nullable=True)
    anomaly_flag = Column(String(200), nullable=True)
    anomaly_resolved = Column(String(1), default="N")
