"""B13 support: outbox scenarios that need a REAL separate OS process (and a real process death).

    python -m tests.integration.b13_outbox_proc <command> [args...]

    enqueue_and_die <message_id> <to>   enqueue + COMMIT the outbox row, then `os._exit(137)` before
                                        any dispatch/delivery - a process crash right after commit
    claim_send_die  <outbox_id>         claim the message, let the (logging) provider accept it, then
                                        `os._exit(137)` before SENT is recorded - a crash mid-delivery
    claim_die       <outbox_id>         claim the message and die before sending anything
    sweep                               run one `deliver_due()` sweep with the configured (logging) sender
    task            <outbox_id>         run the real Celery task body (`email_outbox.deliver_message`)
    start_at=<epoch>                    optional last argument: wait until that instant before acting

Prints one JSON line (except for the `*_die` commands). Strict isolation check first, as in `b13_mp`.
"""

# ruff: noqa: E501 - usage table in the docstring

import asyncio
import json
import os
import sys
import time
from uuid import UUID

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


class _DieAfterAccept:
    """Logging provider (writes `email_log`, contacts nobody), then the process is killed."""

    async def send(self, **kwargs: str) -> None:
        from hrms.modules.onboarding.email_sender import LoggingEmailSender

        await LoggingEmailSender().send(**kwargs)  # type: ignore[arg-type]
        os._exit(137)


class _DieBeforeAccept:
    async def send(self, **kwargs: str) -> None:
        os._exit(137)


async def _main(argv: list[str]) -> object:
    from hrms.core.db.session import dispose_engine, get_session_factory
    from hrms.modules.onboarding import email_outbox as ob

    cmd = argv[0]
    try:
        if cmd == "enqueue_and_die":
            async with get_session_factory()() as session:
                await ob.enqueue_email(
                    session,
                    message_id=argv[1],
                    kind="b13.crash",
                    failure_kind="b13_crash",
                    to=argv[2],
                    subject="crash test",
                    html_body="<p>x</p>",
                    text_body="x",
                    context={"case_id": "crash"},
                )
                await session.commit()
            os._exit(
                137
            )  # never reaches run_post_commit: the dispatch hint is lost with the process
        if cmd == "claim_send_die":
            await ob.deliver_message(UUID(argv[1]), sender=_DieAfterAccept())  # type: ignore[arg-type]
        if cmd == "claim_die":
            await ob.deliver_message(UUID(argv[1]), sender=_DieBeforeAccept())  # type: ignore[arg-type]
        if cmd == "sweep":
            return await ob.deliver_due()
        if cmd == "task":
            from hrms.modules.onboarding.tasks import deliver_outbox_message

            return await asyncio.to_thread(
                lambda: deliver_outbox_message.apply(args=[argv[1]]).get()
            )
        raise SystemExit(f"unknown command {cmd}")
    finally:
        await dispose_engine()


if __name__ == "__main__":
    _isolation()
    args = sys.argv[1:]
    if args and args[-1].startswith("start_at="):
        delay = float(args.pop().split("=", 1)[1]) - time.time()
        if delay > 0:
            time.sleep(delay)
    print(json.dumps(asyncio.run(_main(args))))
