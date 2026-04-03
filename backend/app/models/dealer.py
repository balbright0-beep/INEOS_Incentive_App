import uuid
from sqlalchemy import Column, String, Enum, Boolean, Numeric, DateTime, func
from app.database import Base

REGIONS = ("northeast", "southeast", "central", "western")


class Dealer(Base):
    __tablename__ = "dealers"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ship_to_code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(300), nullable=False)
    region = Column(Enum(*REGIONS, name="region_enum"), nullable=False)
    rbm = Column(String(200), nullable=True)
    state = Column(String(2), nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    model_year = Column(String(10), nullable=False)
    body_style = Column(String(50), nullable=False)
    trim = Column(String(100), nullable=False)
    special_edition = Column(String(100), nullable=True)
    msrp = Column(Numeric(10, 2), nullable=True)
    active = Column(Boolean, default=True)
