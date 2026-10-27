"""Storage calls feed hrms_dependency_* without labelling keys, buckets or payloads."""

import pytest
from prometheus_client import REGISTRY

from hrms.core.storage import _storage_category, _track_storage


def _value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, {"dependency": "storage", **labels}) or 0.0


class _ClientError(Exception):
    def __init__(self, code: str) -> None:
        self.response = {"Error": {"Code": code, "Message": "secret-key-name"}}


def test_success_counts_call() -> None:
    before = _value("hrms_dependency_calls_total", outcome="success")
    with _track_storage():
        pass
    assert _value("hrms_dependency_calls_total", outcome="success") == before + 1


def test_failure_counts_error_with_bounded_category() -> None:
    calls = _value("hrms_dependency_calls_total", outcome="failure")
    errors = _value("hrms_dependency_errors_total", category="dependency_unreachable")
    with pytest.raises(ConnectionError), _track_storage():
        raise ConnectionError("boom")
    assert _value("hrms_dependency_calls_total", outcome="failure") == calls + 1
    assert _value("hrms_dependency_errors_total", category="dependency_unreachable") == errors + 1


def test_missing_object_is_not_an_outage() -> None:
    errors = sum(
        s.value
        for m in REGISTRY.collect()
        if m.name == "hrms_dependency_errors"
        for s in m.samples
        if s.labels.get("dependency") == "storage" and s.name.endswith("_total")
    )
    with pytest.raises(_ClientError), _track_storage():
        raise _ClientError("NoSuchKey")
    after = sum(
        s.value
        for m in REGISTRY.collect()
        if m.name == "hrms_dependency_errors"
        for s in m.samples
        if s.labels.get("dependency") == "storage" and s.name.endswith("_total")
    )
    assert after == errors


def test_provider_error_category_ignores_message() -> None:
    # The message carries a secret-looking key name; only the code may influence the category.
    assert _storage_category(_ClientError("InternalError")) == "provider_error"


@pytest.mark.parametrize(
    ("code", "category"),
    [
        ("XMinioStorageFull", "storage_full"),
        ("InsufficientStorage", "storage_full"),
        ("AccessDenied", "storage_auth"),
        ("InvalidAccessKeyId", "storage_auth"),
        ("SignatureDoesNotMatch", "storage_auth"),
        ("NoSuchBucket", "storage_config"),
        ("SlowDown", "provider_error"),
        ("NoSuchKey", None),
    ],
)
def test_actionable_store_answers_get_their_own_bounded_category(
    code: str, category: str | None
) -> None:
    assert _storage_category(_ClientError(code)) == category


def test_full_store_is_counted_as_a_failure_with_its_category() -> None:
    before = _value("hrms_dependency_errors_total", category="storage_full")
    with pytest.raises(_ClientError), _track_storage():
        raise _ClientError("XMinioStorageFull")
    assert _value("hrms_dependency_errors_total", category="storage_full") == before + 1
