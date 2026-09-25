"""W2 — Shift + Break System: new `shift_version`, `shift_break`, `shift_duty_block` tables.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §9-§10 and the approved W2 plan:
splits the existing mutable `shift` master into an **identity** row (name/code/active — never
changes meaning) and an immutable, effective-dated **`shift_version`** (the actual schedule:
type, timing, breaks, duty blocks). This is the same shape `AttendancePolicy` will eventually
take (W3) and mirrors `policy_assignment`'s insert-new/close-previous idiom exactly.

`shift` itself is never `ALTER`ed by this migration — only three new tables are created, so
`downgrade()` (which drops all three, children first) is trivially safe and
upgrade->downgrade->upgrade-again is a clean cycle with no data loss risk to `shift`.

**`shift_version`** (parent = `shift_id`, admin identity stays on `shift`): `status`
(`DRAFT`|`PUBLISHED`), `effective_from`/`effective_to` (open-ended, `effective_to` only ever
set when a *later* version publishes and closes this one — the one permitted mutation to a
published row), `shift_type` (`FIXED`|`FLEXIBLE`|`SPLIT`), type-specific timing columns,
informational `scheduled_minutes` trio, server-derived `is_night_shift`/`is_cross_midnight`
flags, `is_ot_eligible`/`operates_on_holiday`/`operates_on_weekly_off`, an optional
`weekly_off_pattern_id` (§9.1 shift-specific offs, table already exists from W1), and publish
metadata. DRAFT rows are exempt from the "shift_type/effective_from required" and
"populated-columns-match-shift_type" CHECKs (`shift_version_published_required_check`) —
SPLIT's "≥2 duty blocks" rule can't be a CHECK (it counts child rows), so it's enforced at the
service layer at publish time only. The partial unique index
`shift_version_one_open_draft_idx` is the "one open draft per shift" mechanism. The GiST
exclusion constraint `shift_version_no_overlap` (this codebase's established no-overlap idiom,
`policy_assignment_no_overlap`/`003_effective_dating_constraints.sql`) is the race-condition
backstop for the insert-new/close-previous publish flow, predicated on
`status='PUBLISHED' AND deleted_at IS NULL` (Postgres supports a predicate clause on `EXCLUDE`
exactly as on a partial index; `btree_gist`, already enabled globally, supplies GiST equality
support for `uuid`).

**`shift_break`**/**`shift_duty_block`**: typed children of `shift_version`, no independent
lifecycle — full-replace on every draft PATCH, frozen (via the parent's immutability) once
published. Both carry their own `company_id` + RLS block, matching this codebase's dominant
child-table convention (`employee_assignment`, `weekly_off_rule`, etc.) rather than relying on
a join through the parent.

**Backfill** (upgrade only touches the three new tables): one `shift_version` row per existing
non-deleted `shift` (`status='PUBLISHED'`, `version=1`, `shift_type='FIXED'`,
`effective_from = shift.created_at::date` — a defensible anchor, no attendance data exists yet
to contradict it — `effective_to=NULL`, timing/flags copied straight across), plus one
`shift_break` row per non-zero `break_minutes_paid`/`break_minutes_unpaid`
(`FLEXIBLE_DURATION`, `window_start/end = shift.start_time/end_time`,
`min=max=scheduled=`the legacy minutes value). Matches architecture §29 step 3 literally.

Revision ID: 20260818140000
Revises: 20260818130000
"""

from alembic import op

revision = "20260818140000"
down_revision = "20260818130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shift_version (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "shift_id" UUID NOT NULL,
            "status" VARCHAR(20) NOT NULL,
            "version" INTEGER NOT NULL DEFAULT 1,
            "effective_from" DATE,
            "effective_to" DATE,
            "shift_type" VARCHAR(20),
            "timezone" VARCHAR(64),
            "start_time" TIME,
            "end_time" TIME,
            "window_start" TIME,
            "window_end" TIME,
            "core_start" TIME,
            "core_end" TIME,
            "required_minutes" INTEGER,
            "scheduled_minutes" INTEGER,
            "min_scheduled_minutes" INTEGER,
            "max_scheduled_minutes" INTEGER,
            "is_night_shift" BOOLEAN NOT NULL DEFAULT false,
            "is_cross_midnight" BOOLEAN NOT NULL DEFAULT false,
            "is_ot_eligible" BOOLEAN NOT NULL DEFAULT false,
            "operates_on_holiday" BOOLEAN NOT NULL DEFAULT false,
            "operates_on_weekly_off" BOOLEAN NOT NULL DEFAULT false,
            "weekly_off_pattern_id" UUID,
            "publish_reason" TEXT,
            "published_at" TIMESTAMPTZ,
            "published_by" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "shift_version_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "shift_version_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "shift_version_shift_id_fkey" FOREIGN KEY ("shift_id")
              REFERENCES "shift"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "shift_version_weekly_off_pattern_id_fkey"
              FOREIGN KEY ("weekly_off_pattern_id")
              REFERENCES "weekly_off_pattern"("id") ON DELETE SET NULL ON UPDATE CASCADE,
            CONSTRAINT "shift_version_published_by_fkey" FOREIGN KEY ("published_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "shift_version_status_check" CHECK (status IN ('DRAFT', 'PUBLISHED')),
            CONSTRAINT "shift_version_shift_type_check"
              CHECK (shift_type IS NULL OR shift_type IN ('FIXED', 'FLEXIBLE', 'SPLIT')),
            CONSTRAINT "shift_version_date_range_check"
              CHECK (effective_to IS NULL OR effective_to >= effective_from),
            -- DRAFT rows are exempt from all of the below — a draft may be incomplete
            -- mid-edit. PUBLISHED rows must carry a shift_type + effective_from, and the
            -- type-specific timing columns required for that shift_type. SPLIT's "at least
            -- 2 duty blocks" can't be expressed here (it counts child rows) — enforced at
            -- publish time in the service layer only.
            CONSTRAINT "shift_version_published_required_check" CHECK (
              status = 'DRAFT' OR (
                shift_type IS NOT NULL
                AND effective_from IS NOT NULL
                AND (
                  (shift_type = 'FIXED' AND start_time IS NOT NULL AND end_time IS NOT NULL)
                  OR (
                    shift_type = 'FLEXIBLE'
                    AND window_start IS NOT NULL
                    AND window_end IS NOT NULL
                    AND required_minutes IS NOT NULL
                  )
                  OR (shift_type = 'SPLIT')
                )
              )
            )
        );

        CREATE INDEX IF NOT EXISTS shift_version_company_id_idx
          ON shift_version (company_id);
        CREATE INDEX IF NOT EXISTS shift_version_shift_id_idx
          ON shift_version (shift_id);

        CREATE UNIQUE INDEX IF NOT EXISTS shift_version_one_open_draft_idx
          ON shift_version (shift_id)
          WHERE status = 'DRAFT' AND deleted_at IS NULL;

        ALTER TABLE shift_version
          DROP CONSTRAINT IF EXISTS shift_version_no_overlap;
        ALTER TABLE shift_version
          ADD CONSTRAINT shift_version_no_overlap
          EXCLUDE USING gist (
            shift_id WITH =,
            daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
          )
          WHERE (status = 'PUBLISHED' AND deleted_at IS NULL);

        ALTER TABLE shift_version ENABLE ROW LEVEL SECURITY;
        ALTER TABLE shift_version FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON shift_version;
        CREATE POLICY tenant_isolation ON shift_version
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS shift_break (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "shift_version_id" UUID NOT NULL,
            "name" VARCHAR(100) NOT NULL,
            "break_kind" VARCHAR(20) NOT NULL,
            "start_time" TIME,
            "end_time" TIME,
            "window_start" TIME,
            "window_end" TIME,
            "min_minutes" INTEGER,
            "max_minutes" INTEGER,
            "scheduled_minutes" INTEGER,
            "is_paid" BOOLEAN NOT NULL DEFAULT false,
            "is_mandatory" BOOLEAN NOT NULL DEFAULT true,
            "allows_split" BOOLEAN NOT NULL DEFAULT false,
            "crosses_midnight" BOOLEAN NOT NULL DEFAULT false,
            "sort_order" INTEGER NOT NULL DEFAULT 0,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "shift_break_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "shift_break_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "shift_break_shift_version_id_fkey" FOREIGN KEY ("shift_version_id")
              REFERENCES "shift_version"("id") ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT "shift_break_kind_check"
              CHECK (break_kind IN ('FIXED_WINDOW', 'FLEXIBLE_DURATION')),
            CONSTRAINT "shift_break_kind_fields_check" CHECK (
              (break_kind = 'FIXED_WINDOW' AND start_time IS NOT NULL AND end_time IS NOT NULL)
              OR (
                break_kind = 'FLEXIBLE_DURATION'
                AND window_start IS NOT NULL
                AND window_end IS NOT NULL
                AND min_minutes IS NOT NULL
                AND max_minutes IS NOT NULL
              )
            ),
            CONSTRAINT "shift_break_min_max_check"
              CHECK (min_minutes IS NULL OR max_minutes IS NULL OR min_minutes <= max_minutes)
        );

        CREATE INDEX IF NOT EXISTS shift_break_company_id_idx
          ON shift_break (company_id);
        CREATE INDEX IF NOT EXISTS shift_break_shift_version_id_idx
          ON shift_break (shift_version_id, sort_order);

        ALTER TABLE shift_break ENABLE ROW LEVEL SECURITY;
        ALTER TABLE shift_break FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON shift_break;
        CREATE POLICY tenant_isolation ON shift_break
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS shift_duty_block (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "shift_version_id" UUID NOT NULL,
            "sequence" INTEGER NOT NULL,
            "start_time" TIME NOT NULL,
            "end_time" TIME NOT NULL,
            "crosses_midnight" BOOLEAN NOT NULL DEFAULT false,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "shift_duty_block_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "shift_duty_block_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "shift_duty_block_shift_version_id_fkey" FOREIGN KEY ("shift_version_id")
              REFERENCES "shift_version"("id") ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT "shift_duty_block_time_range_check"
              CHECK (end_time > start_time OR crosses_midnight),
            CONSTRAINT "shift_duty_block_version_sequence_key"
              UNIQUE ("shift_version_id", "sequence")
        );

        CREATE INDEX IF NOT EXISTS shift_duty_block_company_id_idx
          ON shift_duty_block (company_id);

        ALTER TABLE shift_duty_block ENABLE ROW LEVEL SECURITY;
        ALTER TABLE shift_duty_block FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON shift_duty_block;
        CREATE POLICY tenant_isolation ON shift_duty_block
          USING (company_id = current_setting('app.company_id', true)::uuid);

        -- Backfill: one PUBLISHED v1 ShiftVersion per existing non-deleted shift, anchored at
        -- the shift's own created_at date (no attendance data exists yet to contradict it).
        INSERT INTO shift_version (
            id, company_id, shift_id, status, version, effective_from, effective_to,
            shift_type, timezone, start_time, end_time,
            window_start, window_end, core_start, core_end, required_minutes,
            scheduled_minutes, min_scheduled_minutes, max_scheduled_minutes,
            is_night_shift, is_cross_midnight, is_ot_eligible,
            operates_on_holiday, operates_on_weekly_off, weekly_off_pattern_id,
            publish_reason, published_at, published_by,
            created_at, updated_at, deleted_at
        )
        SELECT
            gen_random_uuid(), s.company_id, s.id, 'PUBLISHED', 1, s.created_at::date, NULL,
            'FIXED', NULL, s.start_time, s.end_time,
            NULL, NULL, NULL, NULL, NULL,
            NULL, NULL, NULL,
            s.is_night_shift, s.is_cross_midnight, s.is_ot_eligible,
            false, false, NULL,
            'Backfilled from legacy shift row', s.created_at, NULL,
            s.created_at, s.updated_at, NULL
        FROM shift s
        WHERE s.deleted_at IS NULL;

        -- Backfill: one FLEXIBLE_DURATION ShiftBreak per non-zero legacy break total, per
        -- architecture §29 step 3 ("min=max=scheduled=the legacy minutes value").
        INSERT INTO shift_break (
            id, company_id, shift_version_id, name, break_kind,
            start_time, end_time, window_start, window_end, min_minutes, max_minutes,
            scheduled_minutes, is_paid, is_mandatory, allows_split, crosses_midnight,
            sort_order, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), s.company_id, sv.id, 'Paid break (migrated)', 'FLEXIBLE_DURATION',
            NULL, NULL, s.start_time, s.end_time, s.break_minutes_paid, s.break_minutes_paid,
            s.break_minutes_paid, true, false, false, false, 0, s.created_at, s.updated_at
        FROM shift s
        JOIN shift_version sv ON sv.shift_id = s.id AND sv.status = 'PUBLISHED'
        WHERE s.deleted_at IS NULL AND s.break_minutes_paid > 0;

        INSERT INTO shift_break (
            id, company_id, shift_version_id, name, break_kind,
            start_time, end_time, window_start, window_end, min_minutes, max_minutes,
            scheduled_minutes, is_paid, is_mandatory, allows_split, crosses_midnight,
            sort_order, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), s.company_id, sv.id, 'Unpaid break (migrated)',
            'FLEXIBLE_DURATION',
            NULL, NULL, s.start_time, s.end_time, s.break_minutes_unpaid, s.break_minutes_unpaid,
            s.break_minutes_unpaid, false, false, false, false, 1, s.created_at, s.updated_at
        FROM shift s
        JOIN shift_version sv ON sv.shift_id = s.id AND sv.status = 'PUBLISHED'
        WHERE s.deleted_at IS NULL AND s.break_minutes_unpaid > 0;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS shift_duty_block;
        DROP TABLE IF EXISTS shift_break;
        DROP TABLE IF EXISTS shift_version;
        """
    )
