"""The log sink must never raise into business code, and must make lost lines observable."""

import io
import json
import sys

import pytest

from hrms.core.observability.logging import _STDOUT, _ResilientStdout, dropped_log_writes


@pytest.fixture(autouse=True)
def _reset_counters() -> None:
    _ResilientStdout.dropped_writes = 0
    _ResilientStdout.reported_drops = 0


def _closed() -> io.StringIO:
    stream = io.StringIO()
    stream.close()
    return stream


def test_a_closed_stdout_is_dropped_and_counted_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", _closed())
    assert _STDOUT.write('{"event": "x"}') == 0
    assert _STDOUT.write("\n") == 0
    _STDOUT.flush()  # must not raise either
    assert dropped_log_writes() >= 2


def test_recovery_emits_one_notice_with_the_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", _closed())
    for _ in range(4):
        _STDOUT.write("lost\n")
    assert dropped_log_writes() == 4

    healthy = io.StringIO()
    monkeypatch.setattr(sys, "stdout", healthy)
    _STDOUT.write('{"event": "next"}')  # mid-line: no notice may be spliced in
    assert healthy.getvalue() == '{"event": "next"}'
    _STDOUT.write("\n")
    _STDOUT.write('{"event": "later"}\n')  # second line: the outage was already reported

    lines = healthy.getvalue().splitlines()
    assert lines[0] == '{"event": "next"}'
    notice = json.loads(lines[1])
    assert notice == {
        "event": "log_writes_dropped",
        "level": "error",
        "newly_dropped": 4,
        "dropped_total": 4,
    }
    assert lines[2] == '{"event": "later"}' and len(lines) == 3


def test_a_second_outage_is_reported_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    for expected_new in (2, 1):
        monkeypatch.setattr(sys, "stdout", _closed())
        for _ in range(expected_new):
            _STDOUT.write("lost\n")
        healthy = io.StringIO()
        monkeypatch.setattr(sys, "stdout", healthy)
        _STDOUT.write("ok\n")
        notice = json.loads(healthy.getvalue().splitlines()[1])
        assert notice["newly_dropped"] == expected_new
