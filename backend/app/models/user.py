import uuid
from sqlalchemy import Column, String, Enum, ForeignKey, Boolean, DateTime, func
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum("admin", "rbm", "retailer", name="user_role"), nullable=False)
    dealer_id = Column(String, ForeignKey("dealers.id"), nullable=True)
    region = Column(String(50), nullable=True)
    name = Column(String(200), nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
