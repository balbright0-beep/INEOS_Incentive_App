"""Santander rate input file uploads.

Stores the raw .xlsx bytes admins upload via the Settings page so the
payment calculator can pick up new rates without a redeploy. Four kinds
matching the four files Santander publishes monthly:

  • apr         — INEOS_APRInput_*.xlsx          (national APR rates)
  • lease       — INEOS_LeaseInput_*.xlsx        (national lease rates + residuals)
  • state_apr   — State_INEOS_APRInput_*.xlsx    (per-state APR overrides)
  • state_lease — State_INEOS_LeaseInput_*.xlsx  (per-state lease overrides)

Only one row per kind — uploading replaces the previous file. Old
versions aren't kept (the user has the source xlsx in their own
filesystem; the DB just needs the current one for lookups).
"""

import uuid
from sqlalchemy import Column, String, LargeBinary, DateTime, func
from app.database import Base


SANTANDER_RATE_FILE_KINDS = ("apr", "lease", "state_apr", "state_lease")


class SantanderRateFile(Base):
    __tablename__ = "santander_rate_files"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # One row per kind; the upload endpoint upserts on this column.
    kind = Column(String(20), unique=True, nullable=False, index=True)
    filename = Column(String(300), nullable=False)
    data = Column(LargeBinary, nullable=False)
    uploaded_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    uploaded_by = Column(String, nullable=True)
