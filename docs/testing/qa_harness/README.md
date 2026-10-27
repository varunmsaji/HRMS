# QA harness (Phase 3) - disposable stack + hermetic runner

Nothing here has been executed against infrastructure yet; see `docs/testing/QA_BASELINE_RESULTS.md` section 9.

* `stack.sh` - `preflight` (read-only; already run), `up`, `guard`, `migrate`, `pytest`, `py`, K-1 experiments, `down --confirm`.
* `guard_check.py` - runs inside the runner; proves effective settings point only at the QA containers and that shared dev
  ports/IPs/names and the internet are unreachable.
* `b1/test_b1_attendance.py` - ATT-PUNCH-001..003, ATT-DAY-001..004 (asserts API + DB + invariant, writes JSONL evidence).
* `b1/k1_privileges.py` - K-1 privilege matrix and rolled-back behavioural probes under the real `hrms_app` role.

Isolation model (v2): a holder container with `--network none` owns a loopback-only network namespace; Postgres, Redis, MinIO and every runner join it via `--network container:`. No bridge, gateway, route, DNS or published port. The runner mounts the repo read-only, masks **every** non-example `.env*` file with /dev/null, drops capabilities, has no Docker socket, and starts Python only through `entry.py` (strict allow-list check first). See `docs/testing/QA_A1_SAFETY_REVIEW.md`.
Data directories live under `/media/varun/varun12/work/staff-spectrum/qa_runs/<RUN_ID>/`; container logs are capped at 5 MB each.

## Stale `.venv` shebangs (proposal only - not applied)
`apps/api/.venv/bin/{pytest,lint-imports,...}` start with `#!/media/varun/varun11/.../python`. The harness never uses
them (`.venv/bin/python -m ...` works). To fix without upgrading anything, after approval:
`UV_PROJECT_ENVIRONMENT=/media/varun/varun12/work/staff-spectrum/venvs/api uv sync --frozen --python 3.12` (new location,
lock-exact), verify `head -1 <venv>/bin/pytest`, run the unit tier, then switch. Needs the uv cache or network and ~1 GB on
the non-root volume. The old venv stays until the new one passes.
