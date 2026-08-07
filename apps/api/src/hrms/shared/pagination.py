from datetime import date
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ResponseMeta(BaseModel):
    request_id: str
    server_time: str | None = None


class PaginationMeta(BaseModel):
    page: int = 1
    per_page: int = 25
    total: int = 0
    total_pages: int = 0
    next_cursor: str | None = None


class DataEnvelope(BaseModel, Generic[T]):
    data: T
    meta: ResponseMeta


class ListEnvelope(BaseModel, Generic[T]):
    data: list[T]
    pagination: PaginationMeta | None = None
    meta: ResponseMeta


class MoneyAmount(BaseModel):
    """Integer minor units + currency (ADR-0006)."""

    amount_minor: Annotated[int, Field(description="Amount in minor units (paise for INR)")]
    currency: Annotated[str, Field(min_length=3, max_length=3)]


class DateRange(BaseModel):
    start: date
    end: date | None = None
