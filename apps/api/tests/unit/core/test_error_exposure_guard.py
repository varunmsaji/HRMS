"""The CI guard `scripts/check_error_exposure.py`: it rejects an exception's text copied into a
user-visible value, accepts logging and the safe forms, and the repository itself is clean."""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_error_exposure.py"
_spec = importlib.util.spec_from_file_location("check_error_exposure", _SCRIPT)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
sys.modules["check_error_exposure"] = guard
_spec.loader.exec_module(guard)


def violations(body: str) -> list[str]:
    src = f"def f():\n    try:\n        work()\n    except Exception as exc:\n{body}\n"
    return [v.sink for v in guard.check_source(src)]


# --- prohibited -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("body", "sink"),
    [
        ("        raise SomeError(str(exc))", "error constructor"),
        ("        raise SomeError(f'failed: {exc}')", "error constructor"),
        ("        raise SomeError(repr(exc))", "error constructor"),
        ("        raise SomeError(exc.message)", "error constructor"),
        ("        raise SomeError('x', details=[{'message': str(exc)}])", "error constructor"),
        ("        message = str(exc)", "message ="),
        ("        error_message = f'{exc}'", "error_message ="),
        ("        row = make(error_message=str(exc))", "error_message="),
        ("        row = make(reason=exc.message)", "reason="),
        ("        data = {'detail': str(exc)}", "'detail':"),
        ("        return Result(message=exc.args[0])", "message="),
    ],
)
def test_exception_text_in_a_user_visible_value_is_rejected(body: str, sink: str) -> None:
    assert sink in violations(body)


# --- permitted ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "body",
    [
        "        _logger.warning('x', error=str(exc))",
        "        logger.error('x', message=str(exc))",
        "        safe_log(_logger.error, 'x', reason=str(exc))",
        "        self._logger.exception('x', detail=repr(exc))",
        "        print(str(exc))",
        "        raise SomeError('A fixed sentence') from exc",
        "        message = 'This row could not be imported.'",
        "        raise SomeError(exc.client_message)",
        "        row = make(error_message='fixed', exception_type=type(exc).__name__)",
        "        counts['failed'] += 1",
        "        code = exc.code",
    ],
)
def test_logging_fixed_text_and_the_safe_form_are_allowed(body: str) -> None:
    assert violations(body) == []


def test_only_handler_variables_are_considered() -> None:
    src = "def f(exc):\n    raise SomeError(str(exc))\n"  # not inside an `except ... as exc`
    assert guard.check_source(src) == []


def test_a_handler_without_a_name_is_ignored() -> None:
    src = (
        "def f():\n    try:\n        work()\n    except Exception:\n        raise SomeError('x')\n"
    )
    assert guard.check_source(src) == []


def test_comments_and_strings_do_not_trigger_it() -> None:
    body = "        # raise SomeError(str(exc))\n        note = 'raise SomeError(str(exc))'"
    assert violations(body) == []


# --- the repository -------------------------------------------------------------------------
def test_the_repository_has_no_unlisted_exposure_and_no_stale_allowlist_entry() -> None:
    remaining, stale = guard.scan()
    assert [v.format() for v in remaining] == []
    assert [f"{a.path}: {a.expression}" for a in stale] == []


def test_every_allowlist_entry_has_a_reason() -> None:
    assert all(a.reason.strip() and len(a.reason) > 20 for a in guard.ALLOWLIST)


def test_a_new_leak_in_a_scanned_tree_is_found(tmp_path: Path) -> None:
    pkg = tmp_path / "modules"
    pkg.mkdir()
    (pkg / "leaky.py").write_text(
        "def f():\n    try:\n        work()\n    except Exception as exc:\n"
        "        raise BadThingError(str(exc))\n"
    )
    remaining, _ = guard.scan(tmp_path)
    assert [v.path for v in remaining] == ["modules/leaky.py"]
