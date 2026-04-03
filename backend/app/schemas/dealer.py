from pydantic import BaseModel
from typing import Optional


class DealerCreate(BaseModel):
    ship_to_code: str
    name: str
    region: str
    rbm: Optional[str] = None
    state: Optional[str] = None
    active: bool = True


class DealerResponse(BaseModel):
    id: str
    ship_to_code: str
    name: str
    region: str
    rbm: Optional[str] = None
    state: Optional[str] = None
    active: bool = True

    class Config:
        from_attributes = True


class ProductCreate(BaseModel):
    model_year: str
    body_style: str
    trim: str
    special_edition: Optional[str] = None
    msrp: Optional[float] = None
    active: bool = True


class ProductResponse(BaseModel):
    id: str
    model_year: str
    body_style: str
    trim: str
    special_edition: Optional[str] = None
    msrp: Optional[float] = None
    active: bool = True

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    username: str
    password: str
    role: str
    name: str
    dealer_id: Optional[str] = None
    region: Optional[str] = None


class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    dealer_id: Optional[str] = None
    region: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = None
