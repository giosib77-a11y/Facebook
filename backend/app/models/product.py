"""Product-ის Pydantic სქემები."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    shop_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    sku: str | None = None
    price: float = Field(default=0, ge=0)
    quantity: int = Field(default=0, ge=0)
    image_url: str | None = None
    is_active: bool = True


class ProductUpdate(BaseModel):
    """ნაწილობრივი განახლება — მხოლოდ გადმოცემული ველები იცვლება."""
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    sku: str | None = None
    price: float | None = Field(default=None, ge=0)
    quantity: int | None = Field(default=None, ge=0)
    image_url: str | None = None
    is_active: bool | None = None


class ProductOut(BaseModel):
    id: uuid.UUID
    shop_id: uuid.UUID
    name: str
    description: str | None = None
    sku: str | None = None
    price: float
    quantity: int
    image_url: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
