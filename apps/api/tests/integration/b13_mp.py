"""B13 support: run ONE HTTP request against the ASGI app in its own OS process.

`python -m tests.integration.b13_mp '<json spec>'` - spec keys: `start_at` (epoch seconds; the
process imports everything first, then sleeps until this instant so that several processes
start together),
`method`, `path`, `headers`, `json`. Prints exactly one JSON line: `{"status": int, "body": ...}`.

Each process has its own interpreter, its own SQLAlchemy engine and its own database connections,
so what the tests built on it prove is cross-process behaviour (Postgres locks), not asyncio
scheduling. The strict isolation check runs first, exactly as `qa_harness/entry.py` does.
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "src")


def _isolation() -> None:
    from tests import isolation_guard

    os.environ["HRMS_QA_STRICT"] = "1"
    try:
        isolation_guard.check(os.environ)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        sys.exit(97)


def _negative_controls() -> None:
    """QA only: when NEGCTL is set the child applies the same in-memory control as the parent."""
    if os.environ.get("NEGCTL"):
        import negctl13

        negctl13.pytest_configure(None)


async def _main(spec: dict) -> dict:  # type: ignore[type-arg]
    from entrypoints.api import app
    from httpx import ASGITransport, AsyncClient

    from hrms.core.db.session import dispose_engine

    _negative_controls()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        delay = float(spec["start_at"]) - time.time()
        if delay > 0:
            await asyncio.sleep(delay)
        response = await client.request(
            spec["method"], spec["path"], headers=spec.get("headers"), json=spec.get("json")
        )
    await dispose_engine()
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return {"status": response.status_code, "body": body}


if __name__ == "__main__":
    _isolation()
    print(json.dumps(asyncio.run(_main(json.loads(sys.argv[1])))))
