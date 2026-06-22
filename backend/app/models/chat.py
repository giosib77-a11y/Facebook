"""ჩატის/ბოტის ტესტ-endpoint-ის სქემები."""
import uuid
from typing import Literal

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: Literal["user", "bot"]
    content: str


class TestChatRequest(BaseModel):
    shop_id: uuid.UUID
    message: str = Field(min_length=1)
    history: list[ChatTurn] = Field(default_factory=list)


class TestChatResponse(BaseModel):
    reply: str
    products_in_context: int
    model: str
