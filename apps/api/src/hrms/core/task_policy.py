"""EH-B-04 — why each background task does or does not retry.

A task either opts in to `IDEMPOTENT_TASK_OPTIONS` (`core/celery_app.py`: late ack, redelivery on
worker loss, bounded retry of transient database failures) or is listed here with the reason it
must not. There is no third state: `tests/unit/core/test_task_retry_policy.py` fails for a task in
neither, so a new task has to be classified when it is written.

"Beat re-fires" means the next scheduled run does the same work, so a failed run costs a delay,
not lost work. Leave tasks carry their own (equivalent) options in `modules/leave/tasks.py`.
"""

NO_RETRY_TASKS: dict[str, str] = {
    # Fan-out entrypoints: they only enqueue per-company tasks (publish failures are isolated and
    # logged per company by `dispatch_per_company`), and Beat re-fires them.
    "attendance.run_daily_calculation": "fan-out; Beat re-fires",
    "attendance.run_recalc_requests": "fan-out; Beat re-fires every 5 minutes",
    "attendance.run_incomplete_reminders": "fan-out; Beat re-fires",
    "attendance.run_manager_daily_digest": "fan-out; Beat re-fires",
    "attendance.run_hr_weekly_digest": "fan-out; Beat re-fires",
    "attendance.run_face_cleanup": "fan-out; Beat re-fires",
    "attendance.run_face_deletions": "fan-out; Beat re-fires every few minutes",
    "employee.run_termination_access_sweep": "fan-out; Beat re-fires",
    # Send e-mail: a blind retry after a partial send would deliver the message twice.
    "attendance.send_incomplete_reminders_company": "sends e-mail; a retry could duplicate it",
    "attendance.send_manager_daily_digest_company": "sends e-mail; a retry could duplicate it",
    "attendance.send_hr_weekly_digest_company": "sends e-mail; a retry could duplicate it",
    "notification.send_push": "sends push messages; a retry could duplicate them",
    # Own durable retry: the outbox leases a message, backs off per failure class and takes over
    # from a dead worker, so Celery-level retry would fight it.
    "email_outbox.deliver_message": "outbox owns retry, backoff and leasing",
    "email_outbox.sweep": "outbox owns retry; runs every minute",
    # Destructive retention: report-only until configured; a failed run is repeated deliberately
    # by the next daily Beat run after a person has looked at the log.
    "attendance.cleanup_face_records_company": "destructive retention; Beat repeats after review",
    # Create-only pipeline: a retry after a partial run would duplicate employees (see
    # `modules/employee_import/tasks.py`).
    "employee_import.process_batch": "create-only; a retry would duplicate employees",
    # Health probes: a retry would only hide a real fault.
    "health.ping": "probe",
    "health.scheduler_heartbeat": "probe; a stale heartbeat is the signal",
}
