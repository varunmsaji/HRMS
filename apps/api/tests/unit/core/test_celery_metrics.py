"""Celery task metrics: every outcome the brief asks to tell apart - never submitted, delayed,
running, retried, failed, succeeded - has its own series."""

from prometheus_client import REGISTRY

from hrms.core.celery_app import celery_app, dispatch_per_company


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@celery_app.task(name="test.metrics_ok")
def _ok() -> int:
    return 1


@celery_app.task(name="test.metrics_flaky", bind=True, max_retries=1, default_retry_delay=0)
def _flaky(self) -> None:  # type: ignore[no-untyped-def]
    raise self.retry(exc=ConnectionError("down"))


@celery_app.task(name="test.metrics_bug")
def _bug() -> None:
    raise ValueError("boom with secret-token-123")


def test_success_is_counted_timed_and_stamped() -> None:
    before = sample("hrms_celery_tasks_finished_total", task="test.metrics_ok", state="SUCCESS")
    started = sample("hrms_celery_tasks_started_total", task="test.metrics_ok")
    _ok.apply()
    assert (
        sample("hrms_celery_tasks_finished_total", task="test.metrics_ok", state="SUCCESS")
        == before + 1
    )
    assert sample("hrms_celery_tasks_started_total", task="test.metrics_ok") == started + 1
    assert sample("hrms_celery_task_duration_seconds_count", task="test.metrics_ok") >= 1
    assert sample("hrms_celery_task_last_success_timestamp_seconds", task="test.metrics_ok") > 1e9


def test_retries_and_final_failure_are_separate_series_classified_by_cause() -> None:
    retries = sample("hrms_celery_task_retries_total", task="test.metrics_flaky")
    failures = sample(
        "hrms_celery_task_failures_total",
        task="test.metrics_flaky",
        category="dependency_unreachable",
    )
    _flaky.apply()
    assert sample("hrms_celery_task_retries_total", task="test.metrics_flaky") == retries + 1
    assert (
        sample(
            "hrms_celery_task_failures_total",
            task="test.metrics_flaky",
            category="dependency_unreachable",
        )
        == failures + 1
    )


def test_a_bug_is_categorised_unexpected_and_its_text_never_reaches_a_series() -> None:
    before = sample(
        "hrms_celery_task_failures_total", task="test.metrics_bug", category="unexpected"
    )
    _bug.apply()
    assert (
        sample("hrms_celery_task_failures_total", task="test.metrics_bug", category="unexpected")
        == before + 1
    )
    from prometheus_client import generate_latest

    from hrms.core.observability.metrics import build_registry

    assert b"secret-token-123" not in generate_latest(build_registry())


def test_publish_is_counted_and_a_broker_outage_is_a_distinct_series() -> None:
    class _BrokerDown:
        name = "test.metrics_dispatch"

        def delay(self, *_a: object) -> None:
            raise ConnectionError("broker unavailable")

    class _Fine:
        name = "test.metrics_dispatch_ok"

        def delay(self, *_a: object) -> None:
            return None

    failures = sample("hrms_celery_publish_failures_total", task="test.metrics_dispatch")
    assert dispatch_per_company(_BrokerDown(), [__import__("uuid").uuid4()]) == 0
    assert (
        sample("hrms_celery_publish_failures_total", task="test.metrics_dispatch") == failures + 1
    )
    assert dispatch_per_company(_Fine(), [__import__("uuid").uuid4()]) == 1


def test_unknown_task_messages_are_counted_without_using_the_name_as_a_label() -> None:
    from celery.signals import task_unknown

    before = sample("hrms_celery_messages_unroutable_total", state="unknown_task")
    task_unknown.send(sender=None, name="attacker.controlled." + "x" * 50, id="1")
    assert sample("hrms_celery_messages_unroutable_total", state="unknown_task") == before + 1
    assert (
        REGISTRY.get_sample_value(
            "hrms_celery_messages_unroutable_total", {"state": "attacker.controlled." + "x" * 50}
        )
        is None
    )
