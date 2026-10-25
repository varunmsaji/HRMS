import math
from datetime import date
from typing import Annotated, Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")

# API-01 pagination contract (docs/audits/ — see final report): offset-based `page`/`per_page`,
# 1-indexed, capped server-side so a caller can never request an arbitrarily large page.
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


class ResponseMeta(BaseModel):
    request_id: str
    server_time: str | None = None


class PaginationMeta(BaseModel):
    page: int = 1
    per_page: int = 25
    total: int = 0
    total_pages: int = 0
    next_cursor: str | None = None


class PageParams(BaseModel):
    """Resolved, validated `page`/`per_page` for one request — pass straight through to the
    repository as `limit=per_page, offset=(page - 1) * per_page`."""

    page: int = 1
    per_page: int = DEFAULT_PAGE_SIZE

    @property
    def limit(self) -> int:
        return self.per_page

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


def pagination_params(
    page: Annotated[int, Query(ge=1, description="1-indexed page number")] = 1,
    per_page: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Rows per page (server-capped)")
    ] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    """Shared FastAPI dependency for every paginated list endpoint (API-01). Out-of-range
    `page`/`per_page` fail FastAPI's own query-param validation (422), before a route body ever
    runs — never silently clamped."""
    return PageParams(page=page, per_page=per_page)


def build_pagination_meta(params: PageParams, *, total: int) -> PaginationMeta:
    total_pages = math.ceil(total / params.per_page) if total > 0 else 0
    return PaginationMeta(
        page=params.page, per_page=params.per_page, total=total, total_pages=total_pages
    )


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


# API audit H-1 - collections that used to return their whole result set. Retrofitting the
# standard 25/100 contract onto them would silently truncate existing clients that call them with
# no paging parameters (the web app does), so these routes keep a deliberately generous default and
# cap: a single response can never exceed BOUNDED_MAX_PAGE_SIZE rows, `pagination` is always
# present so a client can detect a partial page, and a client that wants smaller pages just sends
# `per_page`. Lower the default once every caller pages.
BOUNDED_DEFAULT_PAGE_SIZE = 500
BOUNDED_MAX_PAGE_SIZE = 500


def bounded_pagination_params(
    page: Annotated[int, Query(ge=1, description="1-indexed page number")] = 1,
    per_page: Annotated[
        int,
        Query(
            ge=1,
            le=BOUNDED_MAX_PAGE_SIZE,
            description=f"Rows per page (default and maximum {BOUNDED_MAX_PAGE_SIZE})",
        ),
    ] = BOUNDED_DEFAULT_PAGE_SIZE,
) -> PageParams:
    return PageParams(page=page, per_page=per_page)


async def fetch_page(
    session: AsyncSession, stmt: Select[Any], params: PageParams
) -> tuple[list[Any], int]:
    """Runs one `SELECT` bounded to `params` and returns `(rows, total)`.

    The statement must already carry a *total* ordering (a unique tie-breaker last) so pages are
    stable and never overlap or skip rows. `total` counts the unbounded statement."""
    total = int(
        (
            await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
        ).scalar_one()
    )
    rows = (await session.execute(stmt.limit(params.limit).offset(params.offset))).scalars().all()
    return list(rows), total
