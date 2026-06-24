"""შეკვეთის (order) Pydantic სქემები."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ORDER_STATUSES = ("new", "processing", "done", "cancelled")


class OrderItem(BaseModel):
    product_id: uuid.UUID | None = None
    name: str = Field(min_length=1)
    price: float = Field(default=0, ge=0)
    quantity: int = Field(ge=1)


class OrderCreate(BaseModel):
    shop_id: uuid.UUID
    customer_name: str = Field(min_length=1, max_length=120)
    customer_phone: str | None = Field(default=None, max_length=40)
    customer_address: str | None = None
    note: str | None = None
    items: list[OrderItem] = Field(min_length=1)


class OrderOut(BaseModel):
    id: uuid.UUID
    shop_id: uuid.UUID
    customer_name: str
    customer_phone: str | None = None
    customer_address: str | None = None
    note: str | None = None
    items: list[OrderItem]
    total: float
    status: str
    created_at: datetime
    updated_at: datetime


class OrderStatusUpdate(BaseModel):
    status: Literal["new", "processing", "done", "cancelled"]
