"""Local, per-module log files (`docs/operations/LOGGING_GUIDE.md`).

The JSON-lines pipeline in `logging.py` has always written to stdout (Docker's bounded
`json-file` driver). This module adds a second, durable sink: the very same, already-redacted
line is also appended to `<LOG_DIR>/<channel>.log` for every channel the event belongs to.

Design decisions (details and trade-offs in the guide):

* **Routing, not handler fan-out.** One event is rendered once and written to *at most one copy
  per file*: its module channel(s), `app.log` (everything, without the traceback) and — for
  ERROR and above — `errors.log` (the only file that carries the traceback). There is no
  Python-logger propagation involved, so a message can never be duplicated by handler stacking,
  and repeated `configure_logging()` calls just replace the sink.
* **Multi-process safe.** The API runs under gunicorn with several workers, the Celery worker is
  prefork, and Beat is a third process, all appending to the same files. Stdlib
  `RotatingFileHandler` is *not* safe there (two processes rotate the same file and one keeps
  writing to the renamed inode). `RotatingLineFile` instead takes an exclusive `flock` on a
  sidecar `.lock` file around "check size → rotate → append", and re-checks that its descriptor
  still points at the live file before every write. Locks and descriptors are per process
  (re-opened after `fork`), so a gunicorn `--preload` fork cannot share a lock with its parent.
* **Never an availability risk.** Every failure (missing directory, permissions, full disk,
  lock error) drops the file copy, counts it, and reports it in-band once the file works again.
  The stdout copy is unaffected. Failing to *set up* file logging is loud (stderr + an
  `file_logging_unavailable` event) and, when `LOG_FILES_REQUIRED=true`, fatal at startup.
* **Bounded.** Size-based rotation with a fixed number of numbered backups, plus an optional age
  limit for rotated backups. Only files named exactly `<known channel>.log.<n>` are ever
  deleted.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import threading
import time
from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # POSIX only; file logging degrades to "unavailable" on platforms without it.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

#: Every file the sink may create. `app` and `errors` are cross-cutting; the rest are modules.
MODULE_CHANNELS: tuple[str, ...] = (
    "api",
    "auth",
    "attendance",
    "leave",
    "payroll",
    "employees",
    "recruitment",
    "documents",
    "notifications",
    "background_jobs",
    "database",
    "platform",
)
ALL_CHANNELS: tuple[str, ...] = ("app", "errors", *MODULE_CHANNELS)
_CHANNEL_SET = frozenset(ALL_CHANNELS)

TRACEBACK_PLACEHOLDER = "[traceback in errors.log]"
_ERROR_LEVELS = frozenset({"error", "critical", "exception"})
_WARNING_UP = frozenset({"warning", "error", "critical", "exception"})

#: Longest-prefix match on the logger name. Names are the module paths structlog loggers are
#: created with (`get_logger(__name__)`), plus the three fixed names `hrms.http`,
#: `hrms.security`, `hrms.business`.
_LOGGER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("hrms.modules.attendance", "attendance"),
    ("hrms.modules.leave", "leave"),
    ("hrms.modules.payroll", "payroll"),
    ("hrms.modules.employee_import", "employees"),
    ("hrms.modules.employee", "employees"),
    ("hrms.modules.organisation", "employees"),
    # There is no recruitment module: candidate-facing onboarding is the closest feature.
    ("hrms.modules.onboarding.email_sender", "notifications"),
    ("hrms.modules.onboarding", "recruitment"),
    ("hrms.modules.account_invite", "auth"),
    ("hrms.modules.identity", "auth"),
    ("hrms.modules.platform", "platform"),
    ("hrms.modules.health", "background_jobs"),
    ("hrms.security", "auth"),
    ("hrms.core.auth", "auth"),
    ("hrms.core.rbac", "auth"),
    ("hrms.core.tenancy", "auth"),
    ("hrms.shared.rate_limit", "auth"),
    ("hrms.core.db", "database"),
    ("hrms.core.storage", "documents"),
    ("hrms.core.uploads", "documents"),
    ("hrms.core.celery_app", "background_jobs"),
    ("hrms.ingestion", "background_jobs"),
    ("hrms.documents", "documents"),
    ("hrms.http", "api"),
    ("hrms.core.errors", "api"),
    ("celery", "background_jobs"),
    ("kombu", "background_jobs"),
)

#: `business.audit_recorded` carries the audited entity; route by it.
_ENTITY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("pay_", "payroll"),
    ("payroll", "payroll"),
    ("salary", "payroll"),
    ("employee_salary", "payroll"),
    ("employee_bank", "payroll"),
    ("employee_compensation", "payroll"),
    ("leave", "leave"),
    ("attendance", "attendance"),
    ("punch", "attendance"),
    ("shift", "attendance"),
    ("overtime", "attendance"),
    ("regularization", "attendance"),
    ("face_", "attendance"),
    ("employee_face", "attendance"),
    ("employee_document", "documents"),
    ("onboarding_document", "documents"),
    ("onboarding", "recruitment"),
    ("employee", "employees"),
    ("employment", "employees"),
    ("department", "employees"),
    ("designation", "employees"),
    ("grade", "employees"),
    ("branch", "employees"),
    ("legal_entity", "employees"),
    ("account_invite", "auth"),
    ("user_company", "auth"),
    ("session", "auth"),
    ("company", "platform"),
)

#: HTTP route template → module, for request-scoped events that are not otherwise tied to one.
_PATH_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), channel)
    for pattern, channel in (
        (r"^/v1/payroll", "payroll"),
        (r"^/v1/(attendance|shifts|rosters|regularization|overtime)", "attendance"),
        (r"^/v1/leave", "leave"),
        (r"^/v1/auth", "auth"),
        (r"^/v1/platform", "platform"),
        (r"^/v1/(public/)?(onboarding|account-invites)", "recruitment"),
        (r"^/v1/employees/.*/documents", "documents"),
        (r"^/v1/(employees|employee-imports)", "employees"),
    )
)

#: Celery task-name prefix → module.
_TASK_PREFIXES: dict[str, str] = {
    "attendance": "attendance",
    "leave": "leave",
    "payroll": "payroll",
    "employee": "employees",
    "employee_import": "employees",
}

_HTTP_LAYER_EVENTS = frozenset(
    {"http_request", "unhandled_exception", "app_error", "db_error", "error_response"}
)


def _by_prefix(value: str, table: Iterable[tuple[str, str]]) -> str | None:
    for prefix, channel in table:
        if value.startswith(prefix):
            return channel
    return None


def _primary_channel(event: Mapping[str, Any]) -> str | None:
    explicit = event.get("channel")
    if isinstance(explicit, str) and explicit in _CHANNEL_SET - {"app", "errors"}:
        return explicit
    name = str(event.get("event", ""))
    if name.startswith("security."):
        return "auth"
    if name.startswith("email."):
        return "notifications"
    if name.startswith("celery_"):
        return "background_jobs"
    if name.startswith(("db_", "readiness_dependency_failed")):
        return "database"
    if name == "business.audit_recorded":
        entity = str(event.get("entity_type", ""))
        return _by_prefix(entity, _ENTITY_PREFIXES)
    logger_name = event.get("logger")
    if isinstance(logger_name, str):
        return _by_prefix(logger_name, _LOGGER_PREFIXES)
    return None


def resolve_channels(event: Mapping[str, Any]) -> tuple[str, ...]:
    """The module channels (excluding `app`/`errors`) an event belongs to, primary first."""
    channels: list[str] = []

    def add(channel: str | None) -> None:
        if channel and channel not in channels:
            channels.append(channel)

    add(_primary_channel(event))

    task_name = event.get("task_name")
    if isinstance(task_name, str):
        add("background_jobs")
        add(_TASK_PREFIXES.get(task_name.split(".", 1)[0]))

    # A failing request is also interesting to the module it was served by.
    path = event.get("http_path")
    level = str(event.get("level", "")).lower()
    failed = level in _WARNING_UP or int(event.get("status_code") or 0) >= 400
    if isinstance(path, str) and event.get("event") in _HTTP_LAYER_EVENTS and failed:
        add(_by_prefix_regex(path))
    return tuple(channels)


def _by_prefix_regex(path: str) -> str | None:
    for pattern, channel in _PATH_RULES:
        if pattern.search(path):
            return channel
    return None


class RotatingLineFile:
    """An append-only line file with size rotation that is safe across processes and threads."""

    #: Rotated-backup age check cadence — a hot file rotates (and prunes) on its own; this keeps a
    #: quiet one from keeping week-old backups forever.
    _PRUNE_EVERY_SECONDS = 3600.0
    #: After a failed open, do not retry on every log call.
    _RETRY_OPEN_AFTER_SECONDS = 5.0

    def __init__(
        self, path: Path, *, max_bytes: int, backup_count: int, retention_days: int = 0
    ) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.backup_count = max(0, backup_count)
        self.retention_days = max(0, retention_days)
        self._name = path.name
        self._backup_re = re.compile(rf"^{re.escape(path.name)}\.(\d+)$")
        self._thread_lock = threading.Lock()
        self._pid = -1
        self._fd: int | None = None
        self._lock_fd: int | None = None
        self._next_prune = 0.0
        self._retry_at = 0.0
        self.dropped_writes = 0
        self._reported_drops = 0

    # -- descriptors ----------------------------------------------------------------------
    def _open(self) -> None:
        """(Re)opens the data file. The lock descriptor is kept: closing it mid-critical-section
        would release the lock another process is waiting for."""
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None
        if self._lock_fd is None:
            lock_path = self.path.with_name(f".{self._name}.lock")
            self._lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o640)
        self._fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
        self._pid = os.getpid()

    def _close(self) -> None:
        for fd in (self._fd, self._lock_fd):
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
        self._fd = self._lock_fd = None

    def close(self) -> None:
        with self._thread_lock:
            self._close()

    def _fd_is_live(self) -> bool:
        """True while `self._fd` still refers to the file currently at `self.path` (another
        process may have rotated it away since we opened it)."""
        try:
            on_disk = os.stat(self.path)
            ours = os.fstat(self._fd)  # type: ignore[arg-type]
        except OSError:
            return False
        return (on_disk.st_ino, on_disk.st_dev) == (ours.st_ino, ours.st_dev)

    # -- rotation / retention (called with the file lock held) -----------------------------
    def _rotate(self) -> None:
        directory = self.path.parent
        if self.backup_count == 0:
            os.ftruncate(self._fd, 0)  # type: ignore[arg-type]
            return
        oldest = directory / f"{self._name}.{self.backup_count}"
        with contextlib.suppress(FileNotFoundError):
            oldest.unlink()
        for index in range(self.backup_count - 1, 0, -1):
            src = directory / f"{self._name}.{index}"
            if src.exists():
                os.replace(src, directory / f"{self._name}.{index + 1}")
        os.replace(self.path, directory / f"{self._name}.1")
        self._open()

    def _prune_aged_backups(self) -> None:
        if not self.retention_days:
            return
        cutoff = time.time() - self.retention_days * 86400
        for candidate in self.path.parent.iterdir():
            if not self._backup_re.match(candidate.name):
                continue  # never touch anything that is not one of our numbered backups
            with contextlib.suppress(OSError):
                if candidate.stat().st_mtime < cutoff:
                    candidate.unlink()

    # -- public ---------------------------------------------------------------------------
    def write(self, line: str) -> bool:
        """Appends one line. Returns False (and counts a dropped write) on any failure."""
        data = line.encode("utf-8", "replace")
        if not data.endswith(b"\n"):
            data += b"\n"
        with self._thread_lock:
            if self._fd is not None and self._pid != os.getpid():
                self._fd = self._lock_fd = None  # inherited across fork: never reuse
            now = time.monotonic()
            try:
                if self._fd is None:
                    if now < self._retry_at:
                        self.dropped_writes += 1
                        return False
                    self._open()
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX)  # type: ignore[arg-type]
                try:
                    if not self._fd_is_live():
                        self._open()
                    size = os.fstat(self._fd).st_size  # type: ignore[arg-type]
                    if self.max_bytes and size > 0 and size + len(data) > self.max_bytes:
                        self._rotate()
                    if self.retention_days and now >= self._next_prune:
                        self._next_prune = now + self._PRUNE_EVERY_SECONDS
                        self._prune_aged_backups()
                    if self.dropped_writes > self._reported_drops:
                        self._write_all(self._drop_notice())
                        self._reported_drops = self.dropped_writes
                    self._write_all(data)
                finally:
                    with contextlib.suppress(OSError):
                        if self._lock_fd is not None:
                            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            except (OSError, ValueError):
                self.dropped_writes += 1
                self._retry_at = time.monotonic() + self._RETRY_OPEN_AFTER_SECONDS
                self._close()
                return False
        return True

    def _write_all(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            written = os.write(self._fd, view)  # type: ignore[arg-type]
            view = view[written:]

    def _drop_notice(self) -> bytes:
        newly = self.dropped_writes - self._reported_drops
        return (
            json.dumps(
                {
                    "event": "log_file_writes_dropped",
                    "level": "error",
                    "logger": "hrms.logging",
                    "file": self._name,
                    "newly_dropped": newly,
                    "dropped_total": self.dropped_writes,
                }
            )
            + "\n"
        ).encode()


@dataclass(frozen=True)
class FileLoggingConfig:
    directory: Path
    max_bytes: int
    backup_count: int
    retention_days: int


class FileLogSink:
    """Routes a rendered event to its files. One instance per `configure_logging()` call."""

    def __init__(self, config: FileLoggingConfig) -> None:
        self.config = config
        self._files: dict[str, RotatingLineFile] = {}
        self._create_lock = threading.Lock()

    def _file(self, channel: str) -> RotatingLineFile:
        existing = self._files.get(channel)
        if existing is not None:
            return existing
        with self._create_lock:
            return self._files.setdefault(
                channel,
                RotatingLineFile(
                    self.config.directory / f"{channel}.log",
                    max_bytes=self.config.max_bytes,
                    backup_count=self.config.backup_count,
                    retention_days=self.config.retention_days,
                ),
            )

    @property
    def dropped_writes(self) -> int:
        return sum(f.dropped_writes for f in self._files.values())

    def close(self) -> None:
        for f in self._files.values():
            f.close()

    def emit(self, event: MutableMapping[str, Any], render: Any) -> None:
        """Writes `event` to every file it belongs to. `render` turns an event dict into a JSON
        line. Never raises."""
        try:
            channels = resolve_channels(event)
            level = str(event.get("level", "")).lower()
            is_error = level in _ERROR_LEVELS
            has_traceback = isinstance(event.get("exception"), str)

            full_line: str | None = None
            stripped_line: str | None = None

            def line(with_traceback: bool) -> str:
                nonlocal full_line, stripped_line
                if with_traceback or not has_traceback:
                    if full_line is None:
                        full_line = render(event)
                    return full_line
                if stripped_line is None:
                    stripped_line = render({**event, "exception": TRACEBACK_PLACEHOLDER})
                return stripped_line

            for channel in channels:
                self._file(channel).write(line(False))
            self._file("app").write(line(False))
            if is_error:
                self._file("errors").write(line(True))
        except Exception:  # noqa: BLE001 — a log call must never fail the caller
            return


# -- process-wide installation -------------------------------------------------------------
_sink: FileLogSink | None = None
_sink_lock = threading.Lock()


def current_sink() -> FileLogSink | None:
    return _sink


def dropped_file_log_writes() -> int:
    sink = _sink
    return sink.dropped_writes if sink is not None else 0


def uninstall_file_sink() -> None:
    global _sink
    with _sink_lock:
        if _sink is not None:
            _sink.close()
        _sink = None


class FileLoggingUnavailableError(RuntimeError):
    pass


def _prepare_directory(directory: Path) -> None:
    """Creates the directory and proves a file can really be written there (a directory that
    exists but is read-only only fails at the first write otherwise)."""
    if fcntl is None:  # pragma: no cover
        raise FileLoggingUnavailableError("file logging requires POSIX file locking (fcntl)")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".write-probe-{os.getpid()}"
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
        os.close(fd)
        probe.unlink()
    except OSError as exc:
        raise FileLoggingUnavailableError(
            f"log directory {directory} is not writable: {type(exc).__name__}: {exc.strerror}"
        ) from exc


def install_file_sink(config: FileLoggingConfig, *, required: bool) -> FileLogSink | None:
    """Installs (replacing any previous) the process-wide sink. On failure: raise when
    `required`, otherwise report on stderr and carry on with stdout-only logging."""
    global _sink
    try:
        _prepare_directory(config.directory)
    except FileLoggingUnavailableError as exc:
        if required:
            raise
        print(
            json.dumps(
                {
                    "event": "file_logging_unavailable",
                    "level": "error",
                    "logger": "hrms.logging",
                    "detail": str(exc),
                    "effect": "logs are written to stdout only",
                }
            ),
            file=sys.stderr,
        )
        uninstall_file_sink()
        return None
    sink = FileLogSink(config)
    with _sink_lock:
        previous, _sink = _sink, sink
    if previous is not None:
        previous.close()
    return sink
