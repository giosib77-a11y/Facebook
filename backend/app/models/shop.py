"""Shop-ის Pydantic სქემები."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ShopCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    currency: str = Field(default="GEL", max_length=8)


class ShopOut(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None = None
    currency: str
    facebook_page_id: str | None = None
    bot_enabled: bool
    knowledge_filename: str | None = None  # ატვირთული PDF-ის სახელი (ცოდნის ნიშანი)
    created_at: datetime
    updated_at: datetime
    # facebook_page_token და knowledge (სრული ტექსტი) განზრახ არ ბრუნდება
