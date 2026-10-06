"""PAY-B05 - a FINALISED / PAID pay run is immutable in the database, not only in the application.

ADR-0005 / decision 15 make a finalised run permanent, and `PayRunRepository` conditions every write
on the run's status - but that is application code. The runtime role `hrms_app` holds blanket
`UPDATE`/`DELETE` on the payroll tables (it needs them before finalisation: recompute replaces the
lines, a draft run is deleted), so any bug, ad-hoc query or compromised credential could rewrite
a paid payslip. Privileges cannot express "only while the parent run is not final", so this adds
row triggers that can:

* `pay_run`          - no DELETE of a FINALISED/PAID run; the only UPDATE of one is the
                       `FINALISED -> PAID` stamp (status, paid_at, paid_by_user_id, version,
                       updated_at - every other column must be unchanged); nothing becomes PAID
                       except from FINALISED; no run is INSERTed already final.
* `pay_run_employee`, `pay_run_line`, `pay_run_arrear` - no INSERT/UPDATE/DELETE while the parent
                       run is FINALISED/PAID. (Finalise writes the payslip details and stamps the
                       arrears *before* it flips the run, so it is unaffected.)
* `pay_adjustment`   - an APPLIED correction (already paid as arrears) cannot be changed or
                       deleted; `PENDING -> APPLIED` may change only the status columns; none is
                       INSERTed as APPLIED. PENDING corrections stay withdrawable.

The guard applies to the runtime role. The schema owner and superusers are exempt, deliberately and
exactly as for `leave_ledger`/`audit_log` (PRA-16): tenant erasure, retention jobs, migrations and
the test harness run as the owner, and the FK actions `ON DELETE SET NULL` on the *_by_user_id
columns run as the owner too. The runtime role cannot disable or drop a trigger (it does not own
the tables).

No data is read or changed by this migration and no privilege is revoked, so it is safe on existing
data; it only constrains future writes. Downgrade drops the triggers and the function.

Revision ID: 20261013090000
Revises: 20261012090000
"""

from alembic import op

revision = "20261013090000"
down_revision = "20261012090000"
branch_labels = None
depends_on = None

_FUNCTIONS = """
CREATE OR REPLACE FUNCTION payroll_is_maintenance_role() RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, pg_temp AS $$
    SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user AND rolsuper)
        OR EXISTS (
            SELECT 1 FROM pg_class c
            WHERE c.oid = 'public.pay_run'::regclass
              AND pg_has_role(current_user, c.relowner, 'USAGE')
        );
$$;

CREATE OR REPLACE FUNCTION payroll_guard_pay_run() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    stamp_columns text[] := ARRAY['status', 'paid_at', 'paid_by_user_id', 'version', 'updated_at'];
    stripped_old jsonb;
    stripped_new jsonb;
    key text;
BEGIN
    IF payroll_is_maintenance_role() THEN
        RETURN COALESCE(NEW, OLD);
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.status IN ('FINALISED', 'PAID') THEN
            RAISE EXCEPTION 'pay run % cannot be created already %', NEW.id, NEW.status
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF OLD.status IN ('FINALISED', 'PAID') THEN
            RAISE EXCEPTION 'pay run % is % and cannot be deleted', OLD.id, OLD.status
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;

    -- UPDATE
    IF NEW.status = 'PAID' AND OLD.status <> 'FINALISED' AND OLD.status <> 'PAID' THEN
        RAISE EXCEPTION 'pay run % cannot become PAID from %', OLD.id, OLD.status
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status IN ('FINALISED', 'PAID') THEN
        stripped_old := to_jsonb(OLD);
        stripped_new := to_jsonb(NEW);
        FOREACH key IN ARRAY stamp_columns LOOP
            stripped_old := stripped_old - key;
            stripped_new := stripped_new - key;
        END LOOP;
        IF OLD.status = 'FINALISED' AND NEW.status = 'PAID' AND stripped_old = stripped_new THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'pay run % is % and immutable', OLD.id, OLD.status
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION payroll_guard_pay_run_child() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    old_status text;
    new_status text;
BEGIN
    IF payroll_is_maintenance_role() THEN
        RETURN COALESCE(NEW, OLD);
    END IF;

    -- A parent that cannot be found is being deleted along with its child (only a DRAFT run can
    -- be - `payroll_guard_pay_run` refuses the rest) or does not exist (the FK rejects it).
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status INTO old_status FROM public.pay_run WHERE id = OLD.pay_run_id;
        IF old_status IN ('FINALISED', 'PAID') THEN
            RAISE EXCEPTION '% row % belongs to a % pay run and is immutable',
                TG_TABLE_NAME, OLD.id, old_status USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status INTO new_status FROM public.pay_run WHERE id = NEW.pay_run_id;
        IF new_status IN ('FINALISED', 'PAID') THEN
            RAISE EXCEPTION '% rows cannot be added to a % pay run', TG_TABLE_NAME, new_status
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE OR REPLACE FUNCTION payroll_guard_pay_adjustment() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    status_columns text[] := ARRAY['status', 'applied_pay_run_id', 'version', 'updated_at'];
    stripped_old jsonb;
    stripped_new jsonb;
    key text;
BEGIN
    IF payroll_is_maintenance_role() THEN
        RETURN COALESCE(NEW, OLD);
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.status = 'APPLIED' THEN
            RAISE EXCEPTION 'a correction cannot be created already APPLIED'
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'APPLIED' THEN
        RAISE EXCEPTION 'correction % is APPLIED (paid as arrears) and immutable', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    IF NEW.status = 'APPLIED' THEN
        stripped_old := to_jsonb(OLD);
        stripped_new := to_jsonb(NEW);
        FOREACH key IN ARRAY status_columns LOOP
            stripped_old := stripped_old - key;
            stripped_new := stripped_new - key;
        END LOOP;
        IF stripped_old <> stripped_new THEN
            RAISE EXCEPTION 'applying correction % may not change its content', OLD.id
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

_TRIGGERS = (
    ("pay_run", "payroll_guard_pay_run", "INSERT OR UPDATE OR DELETE"),
    ("pay_run_employee", "payroll_guard_pay_run_child", "INSERT OR UPDATE OR DELETE"),
    ("pay_run_line", "payroll_guard_pay_run_child", "INSERT OR UPDATE OR DELETE"),
    ("pay_run_arrear", "payroll_guard_pay_run_child", "INSERT OR UPDATE OR DELETE"),
    ("pay_adjustment", "payroll_guard_pay_adjustment", "INSERT OR UPDATE OR DELETE"),
)


def upgrade() -> None:
    op.execute(_FUNCTIONS)
    for table, function, events in _TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable_guard ON {table};")
        op.execute(
            f"""
            CREATE TRIGGER {table}_immutable_guard
            BEFORE {events} ON {table}
            FOR EACH ROW EXECUTE FUNCTION {function}();
            """
        )


def downgrade() -> None:
    for table, _function, _events in _TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable_guard ON {table};")
    for function in (
        "payroll_guard_pay_adjustment",
        "payroll_guard_pay_run_child",
        "payroll_guard_pay_run",
        "payroll_is_maintenance_role",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}() CASCADE;")
