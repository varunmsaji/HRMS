"""Unit tests for the shared API-01 pagination contract (`hrms/shared/pagination.py`)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hrms.shared.pagination import (
    MAX_PAGE_SIZE,
    PageParams,
    build_pagination_meta,
    pagination_params,
)


def test_page_params_computes_limit_and_offset() -> None:
    params = PageParams(page=3, per_page=10)
    assert params.limit == 10
    assert params.offset == 20


def test_page_params_defaults() -> None:
    params = PageParams()
    assert params.page == 1
    assert params.per_page == 25
    assert params.offset == 0


@pytest.mark.parametrize(
    ("total", "per_page", "expected_total_pages"),
    [
        (0, 25, 0),
        (1, 25, 1),
        (25, 25, 1),
        (26, 25, 2),
        (100, 25, 4),
        (101, 25, 5),
    ],
)
def test_build_pagination_meta_total_pages(
    total: int, per_page: int, expected_total_pages: int
) -> None:
    meta = build_pagination_meta(PageParams(page=1, per_page=per_page), total=total)
    assert meta.total_pages == expected_total_pages
    assert meta.total == total
    assert meta.per_page == per_page
    assert meta.next_cursor is None


def test_pagination_params_dependency_rejects_out_of_range() -> None:
    app = FastAPI()

    from typing import Annotated

    from fastapi import Depends

    @app.get("/items")
    def list_items(page: Annotated[PageParams, Depends(pagination_params)]):
        return {"page": page.page, "per_page": page.per_page}

    client = TestClient(app)

    assert client.get("/items").status_code == 200
    assert client.get("/items", params={"page": 0}).status_code == 422
    assert client.get("/items", params={"page": -1}).status_code == 422
    assert client.get("/items", params={"per_page": 0}).status_code == 422
    assert client.get("/items", params={"per_page": MAX_PAGE_SIZE + 1}).status_code == 422

    ok = client.get("/items", params={"page": 2, "per_page": MAX_PAGE_SIZE})
    assert ok.status_code == 200
    assert ok.json() == {"page": 2, "per_page": MAX_PAGE_SIZE}
