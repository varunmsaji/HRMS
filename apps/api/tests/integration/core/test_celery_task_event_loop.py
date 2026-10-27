"""Regression: consecutive Celery task bodies in ONE worker process must not share asyncpg
connections across event loops.

Each task body runs under its own `asyncio.run()` loop while the engine/pool is process-global.
Before `run_task` disposed the engine inside the task's loop, the second task to run in a worker
process failed with "attached to a different loop" / "Event loop is closed" depending on which
task ran before it - found by running a real worker (the other task tests call the coroutine
directly, so they never crossed a loop boundary). Plain sync tests, like `test_attendance_tasks.py`:
`run_task` owns the event loop, so these cannot be `async def`.
"""

from uuid import uuid4

from sqlalchemy import text

from hrms.core.db.session import run_task, session_scope
from hrms.core.errors.base import NotFoundError
from hrms.modules.attendance import tasks as attendance_tasks
from hrms.modules.leave import tasks as leave_tasks


async def _select_one() -> int:
    async with session_scope() as session:
        return int((await session.execute(text("SELECT 1"))).scalar_one())


def test_run_task_survives_back_to_back_runs_in_one_process() -> None:
    assert [run_task(_select_one()) for _ in range(4)] == [1, 1, 1, 1]


def test_run_task_disposes_the_pool_even_when_the_body_raises() -> None:
    async def boom() -> None:
        await _select_one()
        raise RuntimeError("task body failed")

    for _ in range(2):
        try:
            run_task(boom())
        except RuntimeError as exc:
            assert "task body failed" in str(exc)
    # the failed runs must not poison the next task
    assert run_task(_select_one()) == 1


def test_real_task_entrypoints_can_run_consecutively() -> None:
    # An unknown tenant raises the (expected) domain NotFoundError after opening a DB session;
    # what this guards is that no *loop* RuntimeError escapes on the 2nd and later runs.
    company_id = str(uuid4())
    for _ in range(3):
        for task in (leave_tasks.accrue_company, attendance_tasks.calculate_company):
            try:
                task.run(company_id)
            except NotFoundError:
                pass
