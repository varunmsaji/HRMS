"""Metrics contract: bounded labels, correct classification of outcomes, safe failure, no leaks.

Runs in single-process mode against the default Prometheus registry (counters are read as deltas
so test order never matters). Multi-process aggregation is tested separately in
`test_metrics_multiprocess.py`.
"""

import json
import re
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY

from hrms.app import create_app
from hrms.core.config.settings import get_settings
from hrms.core.errors.base import ConflictError
from hrms.core.observability import metrics as m
from hrms.core.observability import scrape
from hrms.core.observability.operations import logged_operation
from hrms.core.observability.security_events import security_event

TOKEN = "t" * 32


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _client(app: FastAPI) -> AsyncClient:
    # httpx's ASGI transport keeps the app on the test's own event loop, so the process-wide
    # asyncpg engine the scrape probe uses is never shared across loops (as TestClient would).
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


@pytest.fixture
async def metrics_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("METRICS_TOKEN", TOKEN)
    get_settings.cache_clear()
    scrape.reset_cache()
    app: FastAPI = create_app()

    @app.get("/__t/things/{thing_id}")
    async def thing(thing_id: str) -> dict[str, str]:
        return {"id": thing_id}

    @app.get("/__t/boom")
    async def boom() -> None:
        raise RuntimeError("secret-internal-detail")

    async with _client(app) as client:
        yield client


# -- label discipline -----------------------------------------------------------------------
def test_every_metric_uses_only_allowed_low_cardinality_labels() -> None:
    for metric in m.ALL_METRICS:
        labels = set(metric._labelnames)  # noqa: SLF001
        assert labels <= m.ALLOWED_LABELS, (metric._name, labels - m.ALLOWED_LABELS)  # noqa: SLF001
    forbidden = {"company_id", "employee_id", "user_id", "request_id", "email", "path", "task_id"}
    assert not (m.ALLOWED_LABELS & forbidden)


def test_status_class_and_method_are_closed_vocabularies() -> None:
    assert [m.status_class(s) for s in (200, 302, 404, 503, 999)] == [
        "2xx", "3xx", "4xx", "5xx", "other",
    ]  # fmt: skip
    before = sample(
        "hrms_http_requests_total", method="OTHER", route="unmatched", status_class="4xx"
    )
    m.record_http("BREW", "unmatched", 404, 0.01)
    assert (
        sample("hrms_http_requests_total", method="OTHER", route="unmatched", status_class="4xx")
        == before + 1
    )


def test_recording_helpers_never_raise() -> None:
    m.safe_count(m.HTTP_REQUESTS, "only-one-label")  # wrong arity
    m.safe_observe(m.HTTP_DURATION, 1.0)  # missing labels
    m.record_http(None, "x", 200, float("nan"))


# -- HTTP ------------------------------------------------------------------------------------
async def test_routes_are_templates_unknown_paths_collapse_and_ids_never_become_labels(
    metrics_app: AsyncClient,
) -> None:
    ident = str(uuid4())
    before = sample(
        "hrms_http_requests_total", method="GET", route="/__t/things/{thing_id}", status_class="2xx"
    )
    assert (await metrics_app.get(f"/__t/things/{ident}")).status_code == 200
    assert (await metrics_app.get(f"/no/such/{ident}")).status_code == 404
    assert (
        sample(
            "hrms_http_requests_total",
            method="GET",
            route="/__t/things/{thing_id}",
            status_class="2xx",
        )
        == before + 1
    )

    body = (await metrics_app.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})).text
    assert ident not in body
    assert 'route="unmatched"' in body


async def test_unhandled_exception_is_a_5xx_and_categorised_without_leaking_text(
    metrics_app: AsyncClient,
) -> None:
    before = sample("hrms_http_unhandled_exceptions_total", category="unexpected")
    assert (await metrics_app.get("/__t/boom")).status_code == 500
    assert sample("hrms_http_unhandled_exceptions_total", category="unexpected") == before + 1
    body = (await metrics_app.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})).text
    assert "secret-internal-detail" not in body


def test_denials_are_counted_by_status() -> None:
    before = sample("hrms_http_denials_total", code="429")
    m.record_http("POST", "/v1/auth/login", 429, 0.01)
    assert sample("hrms_http_denials_total", code="429") == before + 1


# -- /metrics access control ---------------------------------------------------------------
async def test_metrics_endpoint_is_closed_without_a_configured_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    get_settings.cache_clear()
    async with _client(create_app()) as client:
        assert (await client.get("/metrics")).status_code == 404
        bearer = {"Authorization": f"Bearer {TOKEN}"}
        assert (await client.get("/metrics", headers=bearer)).status_code == 404


async def test_metrics_endpoint_requires_the_bearer_token(metrics_app: AsyncClient) -> None:
    assert (await metrics_app.get("/metrics")).status_code == 401
    assert (
        await metrics_app.get("/metrics", headers={"Authorization": "Bearer nope"})
    ).status_code == 401
    assert (
        await metrics_app.get("/metrics", headers={"Authorization": f"Basic {TOKEN}"})
    ).status_code == 401
    ok = await metrics_app.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("text/plain")
    assert "hrms_http_requests_total" in ok.text


async def test_rejected_scrapes_are_counted_but_successful_ones_are_not(
    metrics_app: AsyncClient,
) -> None:
    denials = sample("hrms_http_denials_total", code="401")
    await metrics_app.get("/metrics", headers={"Authorization": "Bearer wrong"})
    assert sample("hrms_http_denials_total", code="401") == denials + 1
    await metrics_app.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert sample("hrms_http_denials_total", code="401") == denials + 1


async def test_metrics_endpoint_is_hidden_from_openapi_and_unmeasured(
    metrics_app: AsyncClient,
) -> None:
    before = sample("hrms_http_requests_total", method="GET", route="/metrics", status_class="2xx")
    await metrics_app.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert (
        sample("hrms_http_requests_total", method="GET", route="/metrics", status_class="2xx")
        == before
    )
    assert "/metrics" not in create_app().openapi()["paths"]


def test_token_must_be_long_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_TOKEN", "short")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="metrics_token"):
        get_settings()


# -- domain operations -----------------------------------------------------------------------
@logged_operation("test.metrics.op")
async def _op(kind: str) -> str:
    if kind == "reject":
        raise ConflictError("business rule")
    if kind == "fail":
        raise RuntimeError("bug")
    return "ok"


@pytest.mark.parametrize(
    ("kind", "outcome", "error_delta"),
    [("ok", "succeeded", 0), ("reject", "rejected", 0), ("fail", "failed", 1)],
)
async def test_business_rejections_are_not_counted_as_errors(
    kind: str, outcome: str, error_delta: int
) -> None:
    before_ops = sample("hrms_operations_total", operation="test.metrics.op", outcome=outcome)
    before_err = sample("hrms_errors_total", source="operation", category="unexpected")
    try:
        await _op(kind)
    except Exception:  # noqa: BLE001
        pass
    assert (
        sample("hrms_operations_total", operation="test.metrics.op", outcome=outcome)
        == before_ops + 1
    )
    assert sample("hrms_errors_total", source="operation", category="unexpected") == (
        before_err + error_delta
    )


def test_security_events_are_counted_by_event_and_level() -> None:
    before = sample("hrms_security_events_total", event="rate_limited", level="warning")
    security_event("rate_limited", level="warning", bucket="login")
    assert sample("hrms_security_events_total", event="rate_limited", level="warning") == before + 1


# -- scrape-time probes fail safe -----------------------------------------------------------
async def test_unreachable_dependencies_become_up_zero_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hrms.core.db.session import dispose_engine

    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/none")
    get_settings.cache_clear()
    await dispose_engine()
    scrape.reset_cache()
    text = (await scrape.render_metrics()).decode()
    assert 'hrms_dependency_up{dependency="database"} 0.0' in text
    assert 'hrms_dependency_up{dependency="redis"} 0.0' in text
    assert "hrms_jobs_probe_up 0.0" in text
    assert "127.0.0.1" not in text
    scrape.reset_cache()
    await dispose_engine()


# -- log pipeline ----------------------------------------------------------------------------
def test_log_events_are_counted_by_level(capsys: pytest.CaptureFixture[str]) -> None:
    from hrms.core.observability.logging import configure_logging, get_logger

    configure_logging()
    before = sample("hrms_log_events_total", level="error")
    get_logger("hrms.test").error("metrics_probe_event")
    assert sample("hrms_log_events_total", level="error") == before + 1
    assert (
        json.loads(capsys.readouterr().out.strip().splitlines()[-1])["event"]
        == "metrics_probe_event"
    )


async def test_label_values_in_exposition_contain_no_identifiers(metrics_app: AsyncClient) -> None:
    await metrics_app.get(f"/__t/things/{uuid4()}")
    body = (await metrics_app.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})).text
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", body)
    sample_lines = [ln for ln in body.splitlines() if not ln.startswith("#")]
    assert not any("@" in ln for ln in sample_lines)
