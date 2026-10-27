"""Multi-process aggregation, proven with real separate interpreter processes - the shape of the
production deployment (several gunicorn workers + Celery children sharing one directory)."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

CHILD = textwrap.dedent(
    """
    import sys
    from hrms.core.observability import metrics as m
    n = int(sys.argv[1])
    for _ in range(n):
        m.record_http("GET", "/v1/ping", 200, 0.02)
    m.safe_count(m.CELERY_PUBLISHED, "leave.run_monthly_accrual")
    m.CELERY_LAST_SUCCESS.labels("leave.run_monthly_accrual").set(float(sys.argv[2]))
    """
)
RENDER = textwrap.dedent(
    """
    from prometheus_client import generate_latest
    from hrms.core.observability.metrics import build_registry
    print(generate_latest(build_registry()).decode())
    """
)


def _run(code: str, mp_dir: Path, *args: str) -> str:
    env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": str(mp_dir), "LOG_TO_FILES": "false"}
    done = subprocess.run(
        [sys.executable, "-I", "-c", code, *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=Path(__file__).resolve().parents[3],
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_counters_sum_across_processes_and_gauges_take_the_max(tmp_path: Path) -> None:
    src = str(Path(__file__).resolve().parents[3] / "src")
    os.environ.setdefault("PYTHONPATH", src)
    _run(CHILD, tmp_path, "3", "100.0")
    _run(CHILD, tmp_path, "4", "250.0")
    out = _run(RENDER, tmp_path)
    assert 'hrms_http_requests_total{method="GET",route="/v1/ping",status_class="2xx"} 7.0' in out
    assert 'hrms_celery_tasks_published_total{task="leave.run_monthly_accrual"} 2.0' in out
    assert (
        'hrms_celery_task_last_success_timestamp_seconds{task="leave.run_monthly_accrual"} 250.0'
        in out
    )
    # Histogram buckets aggregate too: 7 observations of 20 ms all fall in the 25 ms bucket.
    assert 'hrms_http_request_duration_seconds_bucket{le="0.025",route="/v1/ping"} 7.0' in out


def test_files_are_named_per_host_and_pid_so_containers_cannot_collide(tmp_path: Path) -> None:
    _run(CHILD, tmp_path, "1", "1.0")
    names = [p.name for p in tmp_path.iterdir()]
    assert names and all("-" in n.split("_", 1)[-1] for n in names), names
