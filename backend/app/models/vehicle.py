"""Vehicle inventory model — populated from the Master File for internal VIN lookup."""

import uuid
from sqlalchemy import Column, String, Numeric, Date, Boolean, DateTime, func, Index
from app.database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vin = Column(String(17), unique=True, nullable=False, index=True)
    model_year = Column(String(10), nullable=True)       # e.g., "MY25", "MY26"
    body_style = Column(String(50), nullable=True)        # "station_wagon" or "quartermaster"
    trim = Column(String(100), nullable=True)             # "Base", "Fieldmaster", etc.
    special_edition = Column(String(100), nullable=True)  # "arcane_works_detour", etc.
    material = Column(String(50), nullable=True)          # SAP material code, e.g., "G01C"
    color_exterior = Column(String(100), nullable=True)
    color_interior = Column(String(100), nullable=True)
    msrp = Column(Numeric(10, 2), nullable=True)
    dealer_ship_to = Column(String(20), nullable=True)    # Allocated dealer
    dealer_name = Column(String(300), nullable=True)
    status = Column(String(50), nullable=True)            # e.g., "In Stock", "In Transit", "Sold", "Demo", "CVP"
    wholesale_date = Column(Date, nullable=True)
    retail_date = Column(Date, nullable=True)
    location = Column(String(100), nullable=True)
    notes = Column(String(500), nullable=True)
    imported_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_vehicles_dealer", "dealer_ship_to"),
        Index("ix_vehicles_status", "status"),
        Index("ix_vehicles_model", "model_year", "body_style"),
    )
