"""PRA-04 — every queue a registered task routes to must be consumed by the production worker.

`employee_import.process_batch` routes to `reports_exports`; the production worker
(`docker-compose.prod.yml`) is started without `-Q`, so it consumes exactly the queues declared
in `task_queues`. Before `task_queues` existed it consumed only `default` and import batches sat
in PENDING forever. A runtime proof (real worker, real import) is recorded in
`docs/audits/LOGGING_ERROR_HANDLING_REMEDIATION_REPORT.md`; this test keeps the configuration
from drifting."""

import re
import shlex
from pathlib import Path

import entrypoints.worker  # noqa: F401 — registers every module's tasks

from hrms.core.celery_app import celery_app

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _declared_queues() -> set[str]:
    return set(celery_app.amqp.queues.keys())


def _task_queue(task_name: str) -> str:
    task = celery_app.tasks[task_name]
    return getattr(task, "queue", None) or celery_app.conf.task_default_queue


def _app_task_names() -> list[str]:
    return sorted(name for name in celery_app.tasks if not name.startswith("celery."))


def test_every_registered_task_routes_to_a_declared_queue() -> None:
    declared = _declared_queues()
    assert {_task_queue(name) for name in _app_task_names()} <= declared


def test_import_task_routes_to_reports_exports_and_others_stay_on_default() -> None:
    assert _task_queue("employee_import.process_batch") == "reports_exports"
    others = {_task_queue(n) for n in _app_task_names() if n != "employee_import.process_batch"}
    assert others == {"default"}


def _compose_command(service: str) -> list[str]:
    text = (_REPO_ROOT / "docker-compose.prod.yml").read_text()
    block = text.split(f"\n  {service}:\n", 1)[1].split("\n  # ", 1)[0]
    match = re.search(r'command: \["sh", "-c", "exec ([^"]+)"\]', block)
    assert match, f"no command found for {service}"
    return shlex.split(match.group(1))


def test_production_worker_consumes_every_declared_queue() -> None:
    argv = _compose_command("worker")
    assert argv[:4] == ["celery", "-A", "entrypoints.worker", "worker"]
    queue_flags = [a for a in argv if a == "-Q" or a.startswith(("-Q", "--queues"))]
    if queue_flags:  # an explicit -Q must then list every declared queue
        idx = argv.index(queue_flags[0])
        value = argv[idx + 1] if argv[idx] in ("-Q", "--queues") else argv[idx].split("=", 1)[-1]
        assert set(value.split(",")) >= _declared_queues()
    # No -Q: Celery consumes `task_queues`, which the tests above tie to every task's route.
