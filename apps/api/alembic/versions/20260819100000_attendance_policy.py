"""W3 (2/4) — new `attendance_policy`, `attendance_policy_version`,
`attendance_policy_hour_band`, `attendance_policy_late_band`,
`attendance_policy_early_departure_band` tables.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §11 and WD-02: mirrors
`shift`/`shift_version`'s identity+immutable-version shape exactly (migration
`20260818140000_shift_version_breaks.py`) — `attendance_policy` is a mutable identity
(name/code/active, never evaluation fields), `attendance_policy_version` is the immutable,
effective-dated evaluation body (DRAFT -> PUBLISHED, one open draft per policy, GiST no-overlap
of published rows per `policy_id`). The three band tables are typed, no-independent-lifecycle
children (full-replace on every draft PATCH, frozen once the parent version publishes) —
non-overlap/ordering of bands is validated in the service layer at publish time, not a DB
constraint, for the same reason `shift_break`/`shift_duty_block` don't GiST-constrain their
children: a draft's full-replace transaction (delete-all, insert-new) must never be
mid-transaction-invalid.

Revision ID: 20260819100000
Revises: 20260819090000
"""

from alembic import op

revision = "20260819100000"
down_revision = "20260819090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_policy (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "name" VARCHAR(150) NOT NULL,
            "code" VARCHAR(30),
            "is_active" BOOLEAN NOT NULL DEFAULT true,
            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "attendance_policy_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_policy_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS attendance_policy_company_id_idx
          ON attendance_policy (company_id);
        CREATE UNIQUE INDEX IF NOT EXISTS attendance_policy_company_code_idx
          ON attendance_policy (company_id, code)
          WHERE code IS NOT NULL AND deleted_at IS NULL;

        ALTER TABLE attendance_policy ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_policy FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_policy;
        CREATE POLICY tenant_isolation ON attendance_policy
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS attendance_policy_version (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "policy_id" UUID NOT NULL,
            "status" VARCHAR(20) NOT NULL,
            "version" INTEGER NOT NULL DEFAULT 1,
            "effective_from" DATE,
            "effective_to" DATE,

            "grace_in_minutes" INTEGER NOT NULL DEFAULT 0,
            "grace_out_minutes" INTEGER NOT NULL DEFAULT 0,
            "punch_rounding" VARCHAR(10) NOT NULL DEFAULT 'NONE',
            "rounding_minutes" INTEGER,
            "missing_punch_behaviour" VARCHAR(30) NOT NULL DEFAULT 'INCOMPLETE',
            "auto_close_after_minutes" INTEGER,
            "auto_close_uses_shift_end" BOOLEAN NOT NULL DEFAULT true,
            "missing_shift_behaviour" VARCHAR(20) NOT NULL DEFAULT 'INCOMPLETE',
            "half_day_split" VARCHAR(20) NOT NULL DEFAULT 'BY_HOURS',
            "half_day_boundary_minutes" INTEGER,
            "multi_punch_mode" VARCHAR(20) NOT NULL DEFAULT 'PAIR_ALL',
            "duplicate_punch_window_seconds" INTEGER NOT NULL DEFAULT 60,
            "core_hours_breach_behaviour" VARCHAR(20) NOT NULL DEFAULT 'FLAG',
            "early_out_uses_core_end" BOOLEAN NOT NULL DEFAULT false,
            "split_shift_block_mandatory" BOOLEAN NOT NULL DEFAULT true,
            "split_shift_missed_block_behaviour" VARCHAR(30) NOT NULL DEFAULT 'HALF_DAY',
            "split_shift_allow_hours_compensation" BOOLEAN NOT NULL DEFAULT false,
            "wfh_requires_punch" BOOLEAN NOT NULL DEFAULT true,
            "on_duty_requires_punch" BOOLEAN NOT NULL DEFAULT false,
            "wfh_uses_shift_hours" BOOLEAN NOT NULL DEFAULT true,
            "work_on_leave_behaviour" VARCHAR(30) NOT NULL DEFAULT 'KEEP_LEAVE',
            "excess_break_behaviour" VARCHAR(20) NOT NULL DEFAULT 'FLAG',
            "late_count_window" VARCHAR(10) NOT NULL DEFAULT 'MONTH',
            "lates_to_half_day_count" INTEGER,
            "early_departure_requires_approval" BOOLEAN NOT NULL DEFAULT false,
            "incomplete_at_lock_behaviour" VARCHAR(20) NOT NULL DEFAULT 'TREAT_ABSENT',

            "publish_reason" TEXT,
            "published_at" TIMESTAMPTZ,
            "published_by" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "attendance_policy_version_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_policy_version_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_policy_version_policy_id_fkey" FOREIGN KEY ("policy_id")
              REFERENCES "attendance_policy"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_policy_version_published_by_fkey" FOREIGN KEY ("published_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_policy_version_status_check"
              CHECK (status IN ('DRAFT', 'PUBLISHED')),
            CONSTRAINT "attendance_policy_version_date_range_check"
              CHECK (effective_to IS NULL OR effective_to >= effective_from),
            CONSTRAINT "attendance_policy_version_published_required_check"
              CHECK (status = 'DRAFT' OR effective_from IS NOT NULL)
        );

        CREATE INDEX IF NOT EXISTS attendance_policy_version_company_id_idx
          ON attendance_policy_version (company_id);
        CREATE INDEX IF NOT EXISTS attendance_policy_version_policy_id_idx
          ON attendance_policy_version (policy_id);

        CREATE UNIQUE INDEX IF NOT EXISTS attendance_policy_version_one_open_draft_idx
          ON attendance_policy_version (policy_id)
          WHERE status = 'DRAFT' AND deleted_at IS NULL;

        ALTER TABLE attendance_policy_version
          DROP CONSTRAINT IF EXISTS attendance_policy_version_no_overlap;
        ALTER TABLE attendance_policy_version
          ADD CONSTRAINT attendance_policy_version_no_overlap
          EXCLUDE USING gist (
            policy_id WITH =,
            daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
          )
          WHERE (status = 'PUBLISHED' AND deleted_at IS NULL);

        ALTER TABLE attendance_policy_version ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_policy_version FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_policy_version;
        CREATE POLICY tenant_isolation ON attendance_policy_version
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS attendance_policy_hour_band (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "policy_version_id" UUID NOT NULL,
            "min_minutes" INTEGER NOT NULL,
            "max_minutes" INTEGER,
            "result_status" VARCHAR(20) NOT NULL,
            "sort_order" INTEGER NOT NULL DEFAULT 0,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "attendance_policy_hour_band_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_policy_hour_band_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_policy_hour_band_version_id_fkey"
              FOREIGN KEY ("policy_version_id")
              REFERENCES "attendance_policy_version"("id") ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT "attendance_policy_hour_band_status_check"
              CHECK (result_status IN ('PRESENT', 'HALF_DAY', 'ABSENT')),
            CONSTRAINT "attendance_policy_hour_band_min_max_check"
              CHECK (min_minutes >= 0 AND (max_minutes IS NULL OR max_minutes >= min_minutes))
        );

        CREATE INDEX IF NOT EXISTS attendance_policy_hour_band_version_id_idx
          ON attendance_policy_hour_band (policy_version_id, sort_order);
        CREATE INDEX IF NOT EXISTS attendance_policy_hour_band_company_id_idx
          ON attendance_policy_hour_band (company_id);

        ALTER TABLE attendance_policy_hour_band ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_policy_hour_band FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_policy_hour_band;
        CREATE POLICY tenant_isolation ON attendance_policy_hour_band
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS attendance_policy_late_band (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "policy_version_id" UUID NOT NULL,
            "min_minutes" INTEGER NOT NULL,
            "max_minutes" INTEGER,
            "classification" VARCHAR(20) NOT NULL,
            "counts_toward_cap" BOOLEAN NOT NULL DEFAULT true,
            "sort_order" INTEGER NOT NULL DEFAULT 0,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "attendance_policy_late_band_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_policy_late_band_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_policy_late_band_version_id_fkey"
              FOREIGN KEY ("policy_version_id")
              REFERENCES "attendance_policy_version"("id") ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT "attendance_policy_late_band_classification_check"
              CHECK (classification IN ('NONE', 'LATE', 'HALF_DAY', 'ABSENT')),
            CONSTRAINT "attendance_policy_late_band_min_max_check"
              CHECK (min_minutes >= 0 AND (max_minutes IS NULL OR max_minutes >= min_minutes))
        );

        CREATE INDEX IF NOT EXISTS attendance_policy_late_band_version_id_idx
          ON attendance_policy_late_band (policy_version_id, sort_order);
        CREATE INDEX IF NOT EXISTS attendance_policy_late_band_company_id_idx
          ON attendance_policy_late_band (company_id);

        ALTER TABLE attendance_policy_late_band ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_policy_late_band FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_policy_late_band;
        CREATE POLICY tenant_isolation ON attendance_policy_late_band
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS attendance_policy_early_departure_band (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "policy_version_id" UUID NOT NULL,
            "min_minutes" INTEGER NOT NULL,
            "max_minutes" INTEGER,
            "classification" VARCHAR(20) NOT NULL,
            "counts_toward_cap" BOOLEAN NOT NULL DEFAULT true,
            "sort_order" INTEGER NOT NULL DEFAULT 0,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "attendance_policy_early_departure_band_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_policy_early_departure_band_company_id_fkey"
              FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_policy_early_departure_band_version_id_fkey"
              FOREIGN KEY ("policy_version_id")
              REFERENCES "attendance_policy_version"("id") ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT "attendance_policy_early_departure_band_classification_check"
              CHECK (classification IN ('NONE', 'EARLY_DEPARTURE', 'HALF_DAY', 'ABSENT')),
            CONSTRAINT "attendance_policy_early_departure_band_min_max_check"
              CHECK (min_minutes >= 0 AND (max_minutes IS NULL OR max_minutes >= min_minutes))
        );

        CREATE INDEX IF NOT EXISTS attendance_policy_early_departure_band_version_id_idx
          ON attendance_policy_early_departure_band (policy_version_id, sort_order);
        CREATE INDEX IF NOT EXISTS attendance_policy_early_departure_band_company_id_idx
          ON attendance_policy_early_departure_band (company_id);

        ALTER TABLE attendance_policy_early_departure_band ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_policy_early_departure_band FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_policy_early_departure_band;
        CREATE POLICY tenant_isolation ON attendance_policy_early_departure_band
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS attendance_policy_early_departure_band;
        DROP TABLE IF EXISTS attendance_policy_late_band;
        DROP TABLE IF EXISTS attendance_policy_hour_band;
        DROP TABLE IF EXISTS attendance_policy_version;
        DROP TABLE IF EXISTS attendance_policy;
        """
    )
