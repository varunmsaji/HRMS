"""Attendance break management V1: break modes, break events, employee overrides.

Revision ID: 20261103090000
Revises: 20261102090000

Purely additive: no existing row is rewritten, no existing column or constraint is dropped
(except the two `request_type` CHECKs, which are widened by one value).

* `shift_break` gains the break mode and its configuration. `mode IS NULL` means "legacy": the
  break keeps its pre-existing behaviour (matched against a punch gap), so every break configured
  before this migration calculates exactly as it did.
* `attendance_break_event` (new) is the append-only START/END event log. Rows are never updated
  (trigger); a correction is a new event that `supersedes_event_id` an earlier one.
* `employee_break_override` (new) is the effective-dated, auditable per-employee override
  (`REPLACE` / `ADD` / `DISABLE`) layered over the shift version's breaks at calculation time.
  The original `shift_break` rows are never touched.
* `attendance_break` / `attendance_day` / `attendance_period_summary` gain the derived break facts.
  The period-summary columns are nullable: NULL = frozen before break management existed.
* `attendance_regularization_request` gains the target of a break correction and its type list
  gains `BREAK_CORRECTION`.
"""

# ruff: noqa: E501 - long SQL

from alembic import op

revision = "20261103090000"
down_revision = "20261102090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- ---------------------------------------------------------------- shift_break
        ALTER TABLE shift_break
          ADD COLUMN IF NOT EXISTS mode VARCHAR(20),
          ADD COLUMN IF NOT EXISTS break_type VARCHAR(20) NOT NULL DEFAULT 'OTHER',
          ADD COLUMN IF NOT EXISTS is_enabled BOOLEAN NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS excess_outcome VARCHAR(20),
          ADD COLUMN IF NOT EXISTS auto_deduct_full BOOLEAN NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS optional_recorded_deducts BOOLEAN NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS optional_scheduled_fallback BOOLEAN NOT NULL DEFAULT false;

        ALTER TABLE shift_break
          ADD CONSTRAINT shift_break_mode_check
            CHECK (mode IS NULL OR mode IN ('MANDATORY_PUNCH', 'AUTO_DEDUCT', 'OPTIONAL_PUNCH')),
          ADD CONSTRAINT shift_break_type_check
            CHECK (break_type IN ('LUNCH', 'TEA', 'REST', 'PRAYER', 'OTHER')),
          ADD CONSTRAINT shift_break_excess_outcome_check
            CHECK (excess_outcome IS NULL
                   OR excess_outcome IN ('RECORD_ONLY', 'EXCEPTION', 'REQUIRE_APPROVAL', 'DEDUCT'));

        -- ---------------------------------------------------------------- attendance_break_event
        CREATE TABLE IF NOT EXISTS attendance_break_event (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "attendance_date" DATE NOT NULL,
            "attendance_day_id" UUID,
            "shift_break_id" UUID,
            "break_name" VARCHAR(100),
            "event_type" VARCHAR(10) NOT NULL,
            "event_time" TIMESTAMPTZ NOT NULL,
            "source" VARCHAR(20) NOT NULL,
            "idempotency_key" VARCHAR(100),
            "recorded_by_user_id" UUID,
            "approved_by_user_id" UUID,
            "supersedes_event_id" UUID,
            "regularization_request_id" UUID,
            "reason" TEXT,
            "meta" JSONB,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "attendance_break_event_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_break_event_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_break_event_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_break_event_attendance_day_id_fkey" FOREIGN KEY ("attendance_day_id")
              REFERENCES "attendance_day"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_break_event_shift_break_id_fkey" FOREIGN KEY ("shift_break_id")
              REFERENCES "shift_break"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_break_event_recorded_by_fkey" FOREIGN KEY ("recorded_by_user_id")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_break_event_approved_by_fkey" FOREIGN KEY ("approved_by_user_id")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_break_event_supersedes_fkey" FOREIGN KEY ("supersedes_event_id")
              REFERENCES "attendance_break_event"("id") ON DELETE RESTRICT,
            CONSTRAINT "attendance_break_event_regularization_fkey" FOREIGN KEY ("regularization_request_id")
              REFERENCES "attendance_regularization_request"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_break_event_type_check" CHECK (event_type IN ('START', 'END')),
            CONSTRAINT "attendance_break_event_source_check"
              CHECK (source IN ('WEB', 'MOBILE', 'ADMIN', 'SYSTEM'))
        );

        CREATE INDEX IF NOT EXISTS attendance_break_event_company_id_idx
          ON attendance_break_event (company_id);
        CREATE INDEX IF NOT EXISTS attendance_break_event_employee_time_idx
          ON attendance_break_event (company_id, employee_id, event_time);
        CREATE INDEX IF NOT EXISTS attendance_break_event_employee_date_idx
          ON attendance_break_event (company_id, employee_id, attendance_date);
        CREATE UNIQUE INDEX IF NOT EXISTS attendance_break_event_idempotency_key_idx
          ON attendance_break_event (company_id, idempotency_key)
          WHERE idempotency_key IS NOT NULL;
        -- One correction per superseded event: two concurrent corrections cannot both win.
        CREATE UNIQUE INDEX IF NOT EXISTS attendance_break_event_supersedes_idx
          ON attendance_break_event (supersedes_event_id)
          WHERE supersedes_event_id IS NOT NULL;

        ALTER TABLE attendance_break_event ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_break_event FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_break_event;
        CREATE POLICY tenant_isolation ON attendance_break_event
          USING (company_id = current_setting('app.company_id', true)::uuid);

        -- Events are immutable once written: corrections are new rows that supersede. The one
        -- permitted UPDATE is a link column (day / shift break / user / request) being set to NULL
        -- by the ON DELETE SET NULL of the row it pointed at — never a change to what happened.
        CREATE OR REPLACE FUNCTION attendance_break_event_immutable() RETURNS trigger AS $fn$
        BEGIN
          IF (NEW.id, NEW.company_id, NEW.employee_id, NEW.attendance_date, NEW.break_name,
              NEW.event_type, NEW.event_time, NEW.source, NEW.idempotency_key,
              NEW.supersedes_event_id, NEW.reason, NEW.meta, NEW.created_at)
             IS DISTINCT FROM
             (OLD.id, OLD.company_id, OLD.employee_id, OLD.attendance_date, OLD.break_name,
              OLD.event_type, OLD.event_time, OLD.source, OLD.idempotency_key,
              OLD.supersedes_event_id, OLD.reason, OLD.meta, OLD.created_at)
             OR (NEW.attendance_day_id IS NOT NULL
                 AND NEW.attendance_day_id IS DISTINCT FROM OLD.attendance_day_id)
             OR (NEW.shift_break_id IS NOT NULL
                 AND NEW.shift_break_id IS DISTINCT FROM OLD.shift_break_id)
             OR (NEW.recorded_by_user_id IS NOT NULL
                 AND NEW.recorded_by_user_id IS DISTINCT FROM OLD.recorded_by_user_id)
             OR (NEW.approved_by_user_id IS NOT NULL
                 AND NEW.approved_by_user_id IS DISTINCT FROM OLD.approved_by_user_id)
             OR (NEW.regularization_request_id IS NOT NULL
                 AND NEW.regularization_request_id IS DISTINCT FROM OLD.regularization_request_id)
          THEN
            RAISE EXCEPTION 'attendance_break_event rows are immutable (id %)', OLD.id
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;
          RETURN NEW;
        END;
        $fn$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS attendance_break_event_no_update ON attendance_break_event;
        CREATE TRIGGER attendance_break_event_no_update
          BEFORE UPDATE ON attendance_break_event
          FOR EACH ROW EXECUTE FUNCTION attendance_break_event_immutable();

        -- ---------------------------------------------------------------- employee_break_override
        CREATE TABLE IF NOT EXISTS employee_break_override (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "shift_id" UUID,
            "action" VARCHAR(10) NOT NULL,
            "target_break_name" VARCHAR(100),
            "shift_break_id" UUID,
            "effective_from" DATE NOT NULL,
            "effective_to" DATE,
            "reason" TEXT NOT NULL,
            "name" VARCHAR(100),
            "break_type" VARCHAR(20),
            "break_kind" VARCHAR(20),
            "mode" VARCHAR(20),
            "start_time" TIME,
            "end_time" TIME,
            "window_start" TIME,
            "window_end" TIME,
            "min_minutes" INTEGER,
            "max_minutes" INTEGER,
            "scheduled_minutes" INTEGER,
            "is_paid" BOOLEAN,
            "is_mandatory" BOOLEAN,
            "crosses_midnight" BOOLEAN,
            "excess_outcome" VARCHAR(20),
            "auto_deduct_full" BOOLEAN,
            "optional_recorded_deducts" BOOLEAN,
            "optional_scheduled_fallback" BOOLEAN,
            "sort_order" INTEGER,
            "created_by" UUID,
            "revoked_at" TIMESTAMPTZ,
            "revoked_by" UUID,
            "revoke_reason" TEXT,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "employee_break_override_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "employee_break_override_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "employee_break_override_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "employee_break_override_shift_id_fkey" FOREIGN KEY ("shift_id")
              REFERENCES "shift"("id") ON DELETE SET NULL,
            CONSTRAINT "employee_break_override_shift_break_id_fkey" FOREIGN KEY ("shift_break_id")
              REFERENCES "shift_break"("id") ON DELETE SET NULL,
            CONSTRAINT "employee_break_override_created_by_fkey" FOREIGN KEY ("created_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "employee_break_override_revoked_by_fkey" FOREIGN KEY ("revoked_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "employee_break_override_action_check"
              CHECK (action IN ('REPLACE', 'ADD', 'DISABLE')),
            CONSTRAINT "employee_break_override_date_range_check"
              CHECK (effective_to IS NULL OR effective_to >= effective_from),
            CONSTRAINT "employee_break_override_target_check" CHECK (
              (action = 'ADD') OR target_break_name IS NOT NULL
            ),
            CONSTRAINT "employee_break_override_mode_check"
              CHECK (mode IS NULL OR mode IN ('MANDATORY_PUNCH', 'AUTO_DEDUCT', 'OPTIONAL_PUNCH')),
            CONSTRAINT "employee_break_override_excess_outcome_check"
              CHECK (excess_outcome IS NULL
                     OR excess_outcome IN ('RECORD_ONLY', 'EXCEPTION', 'REQUIRE_APPROVAL', 'DEDUCT'))
        );

        CREATE INDEX IF NOT EXISTS employee_break_override_company_id_idx
          ON employee_break_override (company_id);
        CREATE INDEX IF NOT EXISTS employee_break_override_employee_idx
          ON employee_break_override (company_id, employee_id, effective_from);

        -- Two live overrides of the same named break must not cover the same day: the resolution
        -- is deterministic only if at most one REPLACE/DISABLE targets a break on any date.
        ALTER TABLE employee_break_override
          DROP CONSTRAINT IF EXISTS employee_break_override_no_overlap;
        ALTER TABLE employee_break_override
          ADD CONSTRAINT employee_break_override_no_overlap
          EXCLUDE USING gist (
            employee_id WITH =,
            lower(target_break_name) WITH =,
            daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
          )
          WHERE (action <> 'ADD' AND revoked_at IS NULL);

        ALTER TABLE employee_break_override ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_break_override FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employee_break_override;
        CREATE POLICY tenant_isolation ON employee_break_override
          USING (company_id = current_setting('app.company_id', true)::uuid);

        -- ---------------------------------------------------------------- attendance_break
        ALTER TABLE attendance_break
          ADD COLUMN IF NOT EXISTS name VARCHAR(100),
          ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'PUNCHED_GAP',
          ADD COLUMN IF NOT EXISTS rule_source VARCHAR(20),
          ADD COLUMN IF NOT EXISTS override_id UUID,
          ADD COLUMN IF NOT EXISTS scheduled_minutes INTEGER,
          ADD COLUMN IF NOT EXISTS excess_minutes INTEGER NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS deducted_minutes INTEGER NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS needs_review BOOLEAN NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS is_approved BOOLEAN NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS start_event_id UUID,
          ADD COLUMN IF NOT EXISTS end_event_id UUID;
        ALTER TABLE attendance_break
          ADD CONSTRAINT attendance_break_kind_check
            CHECK (kind IN ('PUNCHED_GAP', 'EVENT', 'AUTO_DEDUCTED', 'UNRESOLVED')),
          ADD CONSTRAINT attendance_break_rule_source_check
            CHECK (rule_source IS NULL OR rule_source IN ('SHIFT', 'EMPLOYEE_OVERRIDE')),
          ADD CONSTRAINT attendance_break_override_id_fkey FOREIGN KEY (override_id)
            REFERENCES employee_break_override(id) ON DELETE SET NULL,
          ADD CONSTRAINT attendance_break_start_event_id_fkey FOREIGN KEY (start_event_id)
            REFERENCES attendance_break_event(id) ON DELETE SET NULL,
          ADD CONSTRAINT attendance_break_end_event_id_fkey FOREIGN KEY (end_event_id)
            REFERENCES attendance_break_event(id) ON DELETE SET NULL;

        -- ---------------------------------------------------------------- attendance_day
        ALTER TABLE attendance_day
          ADD COLUMN IF NOT EXISTS actual_break_minutes INTEGER NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS auto_deducted_break_minutes INTEGER NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS unresolved_break_count INTEGER NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS has_unresolved_break BOOLEAN NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS has_active_break BOOLEAN NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS has_excess_break_exception BOOLEAN NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS gross_elapsed_minutes INTEGER NOT NULL DEFAULT 0;
        CREATE INDEX IF NOT EXISTS attendance_day_unresolved_break_idx
          ON attendance_day (company_id, attendance_date)
          WHERE has_unresolved_break OR has_excess_break_exception;

        -- ---------------------------------------------------------------- attendance_period_summary
        ALTER TABLE attendance_period_summary
          ADD COLUMN IF NOT EXISTS paid_break_minutes_total INTEGER,
          ADD COLUMN IF NOT EXISTS unpaid_break_minutes_total INTEGER,
          ADD COLUMN IF NOT EXISTS auto_deducted_break_minutes_total INTEGER,
          ADD COLUMN IF NOT EXISTS actual_break_minutes_total INTEGER,
          ADD COLUMN IF NOT EXISTS excess_break_minutes_total INTEGER,
          ADD COLUMN IF NOT EXISTS unresolved_break_days INTEGER;

        -- ---------------------------------------------------------------- regularization
        ALTER TABLE attendance_regularization_request
          ADD COLUMN IF NOT EXISTS break_start_event_id UUID,
          ADD COLUMN IF NOT EXISTS requested_break_end TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS requested_break_minutes INTEGER;
        ALTER TABLE attendance_regularization_request
          ADD CONSTRAINT attendance_regularization_request_break_start_fkey
            FOREIGN KEY (break_start_event_id) REFERENCES attendance_break_event(id)
            ON DELETE SET NULL;

        ALTER TABLE attendance_regularization_request
          DROP CONSTRAINT IF EXISTS attendance_regularization_request_request_type_check;
        ALTER TABLE attendance_regularization_request
          ADD CONSTRAINT attendance_regularization_request_request_type_check CHECK (
            request_type IN (
              'MISSING_PUNCH', 'WRONG_PUNCH', 'WRONG_SHIFT', 'WRONG_STATUS',
              'WFH', 'ON_DUTY', 'EXCESS_BREAK', 'FULL_DAY', 'BREAK_CORRECTION'
            )
          );
        ALTER TABLE regularization_policy_allowed_type
          DROP CONSTRAINT IF EXISTS regularization_policy_allowed_type_check;
        ALTER TABLE regularization_policy_allowed_type
          ADD CONSTRAINT regularization_policy_allowed_type_check CHECK (
            regularization_type IN (
              'MISSING_PUNCH', 'WRONG_PUNCH', 'WRONG_SHIFT', 'WRONG_STATUS', 'WFH',
              'ON_DUTY', 'EXCESS_BREAK', 'FULL_DAY', 'BREAK_CORRECTION'
            )
          );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE regularization_policy_allowed_type
          DROP CONSTRAINT IF EXISTS regularization_policy_allowed_type_check;
        DELETE FROM regularization_policy_allowed_type WHERE regularization_type = 'BREAK_CORRECTION';
        ALTER TABLE regularization_policy_allowed_type
          ADD CONSTRAINT regularization_policy_allowed_type_check CHECK (
            regularization_type IN (
              'MISSING_PUNCH', 'WRONG_PUNCH', 'WRONG_SHIFT', 'WRONG_STATUS', 'WFH',
              'ON_DUTY', 'EXCESS_BREAK', 'FULL_DAY'
            )
          );

        ALTER TABLE attendance_regularization_request
          DROP CONSTRAINT IF EXISTS attendance_regularization_request_request_type_check,
          DROP CONSTRAINT IF EXISTS attendance_regularization_request_break_start_fkey;
        DELETE FROM attendance_regularization_request WHERE request_type = 'BREAK_CORRECTION';
        ALTER TABLE attendance_regularization_request
          ADD CONSTRAINT attendance_regularization_request_request_type_check CHECK (
            request_type IN (
              'MISSING_PUNCH', 'WRONG_PUNCH', 'WRONG_SHIFT', 'WRONG_STATUS',
              'WFH', 'ON_DUTY', 'EXCESS_BREAK', 'FULL_DAY'
            )
          ),
          DROP COLUMN IF EXISTS break_start_event_id,
          DROP COLUMN IF EXISTS requested_break_end,
          DROP COLUMN IF EXISTS requested_break_minutes;

        ALTER TABLE attendance_period_summary
          DROP COLUMN IF EXISTS paid_break_minutes_total,
          DROP COLUMN IF EXISTS unpaid_break_minutes_total,
          DROP COLUMN IF EXISTS auto_deducted_break_minutes_total,
          DROP COLUMN IF EXISTS actual_break_minutes_total,
          DROP COLUMN IF EXISTS excess_break_minutes_total,
          DROP COLUMN IF EXISTS unresolved_break_days;

        DROP INDEX IF EXISTS attendance_day_unresolved_break_idx;
        ALTER TABLE attendance_day
          DROP COLUMN IF EXISTS actual_break_minutes,
          DROP COLUMN IF EXISTS auto_deducted_break_minutes,
          DROP COLUMN IF EXISTS unresolved_break_count,
          DROP COLUMN IF EXISTS has_unresolved_break,
          DROP COLUMN IF EXISTS has_active_break,
          DROP COLUMN IF EXISTS has_excess_break_exception,
          DROP COLUMN IF EXISTS gross_elapsed_minutes;

        ALTER TABLE attendance_break
          DROP CONSTRAINT IF EXISTS attendance_break_kind_check,
          DROP CONSTRAINT IF EXISTS attendance_break_rule_source_check,
          DROP CONSTRAINT IF EXISTS attendance_break_override_id_fkey,
          DROP CONSTRAINT IF EXISTS attendance_break_start_event_id_fkey,
          DROP CONSTRAINT IF EXISTS attendance_break_end_event_id_fkey,
          DROP COLUMN IF EXISTS name,
          DROP COLUMN IF EXISTS kind,
          DROP COLUMN IF EXISTS rule_source,
          DROP COLUMN IF EXISTS override_id,
          DROP COLUMN IF EXISTS scheduled_minutes,
          DROP COLUMN IF EXISTS excess_minutes,
          DROP COLUMN IF EXISTS deducted_minutes,
          DROP COLUMN IF EXISTS needs_review,
          DROP COLUMN IF EXISTS is_approved,
          DROP COLUMN IF EXISTS start_event_id,
          DROP COLUMN IF EXISTS end_event_id;

        DROP TABLE IF EXISTS employee_break_override;
        DROP TABLE IF EXISTS attendance_break_event;
        DROP FUNCTION IF EXISTS attendance_break_event_immutable();

        ALTER TABLE shift_break
          DROP CONSTRAINT IF EXISTS shift_break_mode_check,
          DROP CONSTRAINT IF EXISTS shift_break_type_check,
          DROP CONSTRAINT IF EXISTS shift_break_excess_outcome_check,
          DROP COLUMN IF EXISTS mode,
          DROP COLUMN IF EXISTS break_type,
          DROP COLUMN IF EXISTS is_enabled,
          DROP COLUMN IF EXISTS excess_outcome,
          DROP COLUMN IF EXISTS auto_deduct_full,
          DROP COLUMN IF EXISTS optional_recorded_deducts,
          DROP COLUMN IF EXISTS optional_scheduled_fallback;
        """
    )
