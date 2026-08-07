-- Doc 04 §1 global rule: gen_random_uuid() (pgcrypto) for PKs, btree_gist for the effective-dating
-- exclusion constraints below. Created here, not only in the container init script, so this
-- migration is self-contained and reproducible against any fresh database (including Prisma's
-- shadow database, which does not run infra/docker/postgres/init/*.sql).
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- CreateTable
CREATE TABLE "company" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "name" VARCHAR(200) NOT NULL,
    "legal_name" VARCHAR(200),
    "subdomain" VARCHAR(63),
    "industry_code" VARCHAR(40),
    "country_code" CHAR(2) NOT NULL DEFAULT 'IN',
    "currency" CHAR(3) NOT NULL DEFAULT 'INR',
    "timezone" VARCHAR(50) NOT NULL DEFAULT 'Asia/Kolkata',
    "fy_start_month" SMALLINT NOT NULL DEFAULT 4,
    "logo_url" TEXT,
    "theme_json" JSONB,
    "status" VARCHAR(20) NOT NULL DEFAULT 'TRIAL',
    "onboarded_at" TIMESTAMPTZ,
    "trial_ends_at" TIMESTAMPTZ,
    "data_region" VARCHAR(20),
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,
    "version" INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT "company_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "user" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "email" VARCHAR(255),
    "phone" VARCHAR(20),
    "password_hash" TEXT,
    "mfa_enabled" BOOLEAN NOT NULL DEFAULT false,
    "status" VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,
    "version" INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT "user_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "user_company" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "is_primary" BOOLEAN NOT NULL DEFAULT false,
    "status" VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "user_company_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "role" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID,
    "code" VARCHAR(60) NOT NULL,
    "name" VARCHAR(120) NOT NULL,
    "is_system" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,

    CONSTRAINT "role_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "permission" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "code" VARCHAR(100) NOT NULL,
    "domain" VARCHAR(40) NOT NULL,
    "description" TEXT,

    CONSTRAINT "permission_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "role_permission" (
    "role_id" UUID NOT NULL,
    "permission_id" UUID NOT NULL,

    CONSTRAINT "role_permission_pkey" PRIMARY KEY ("role_id","permission_id")
);

-- CreateTable
CREATE TABLE "user_role" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_company_id" UUID NOT NULL,
    "role_id" UUID NOT NULL,

    CONSTRAINT "user_role_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "session" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "company_id" UUID,
    "ip_address" VARCHAR(45),
    "user_agent" TEXT,
    "expires_at" TIMESTAMPTZ NOT NULL,
    "revoked_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "session_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "refresh_token" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "token_hash" TEXT NOT NULL,
    "expires_at" TIMESTAMPTZ NOT NULL,
    "revoked_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "refresh_token_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "legal_entity" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "name" VARCHAR(200) NOT NULL,
    "pan" VARCHAR(20),
    "gstin" VARCHAR(20),
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,

    CONSTRAINT "legal_entity_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "branch" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "legal_entity_id" UUID NOT NULL,
    "name" VARCHAR(200) NOT NULL,
    "state" VARCHAR(60),
    "timezone" VARCHAR(50),
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,

    CONSTRAINT "branch_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "department" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "branch_id" UUID,
    "name" VARCHAR(150) NOT NULL,
    "code" VARCHAR(30),
    "parent_id" UUID,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,

    CONSTRAINT "department_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "designation" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "department_id" UUID,
    "title" VARCHAR(150) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,

    CONSTRAINT "designation_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "grade" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "code" VARCHAR(30) NOT NULL,
    "name" VARCHAR(100) NOT NULL,
    "rank" INTEGER,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,

    CONSTRAINT "grade_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "holiday_calendar" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "name" VARCHAR(150) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,

    CONSTRAINT "holiday_calendar_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "holiday" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "calendar_id" UUID NOT NULL,
    "date" DATE NOT NULL,
    "name" VARCHAR(150) NOT NULL,
    "is_optional" BOOLEAN NOT NULL DEFAULT false,

    CONSTRAINT "holiday_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "employee" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "user_id" UUID,
    "employee_code" VARCHAR(30) NOT NULL,
    "first_name" VARCHAR(100) NOT NULL,
    "last_name" VARCHAR(100),
    "date_of_birth" DATE,
    "gender" VARCHAR(20),
    "custom_fields" JSONB,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,
    "version" INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT "employee_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "employment" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "employee_id" UUID NOT NULL,
    "legal_entity_id" UUID NOT NULL,
    "joining_date" DATE NOT NULL,
    "exit_date" DATE,
    "status" VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,

    CONSTRAINT "employment_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "employee_assignment" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "employee_id" UUID NOT NULL,
    "department_id" UUID,
    "designation_id" UUID,
    "grade_id" UUID,
    "reporting_manager_id" UUID,
    "branch_id" UUID,
    "effective_from" DATE NOT NULL,
    "effective_to" DATE,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,
    "version" INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT "employee_assignment_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "employee_compensation" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "employee_id" UUID NOT NULL,
    "annual_ctc_minor" BIGINT NOT NULL,
    "currency" CHAR(3) NOT NULL DEFAULT 'INR',
    "effective_from" DATE NOT NULL,
    "effective_to" DATE,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,
    "version" INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT "employee_compensation_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "company_subdomain_key" ON "company"("subdomain");

-- CreateIndex
CREATE UNIQUE INDEX "user_email_key" ON "user"("email");

-- CreateIndex
CREATE UNIQUE INDEX "user_phone_key" ON "user"("phone");

-- CreateIndex
CREATE INDEX "user_company_company_id_idx" ON "user_company"("company_id");

-- CreateIndex
CREATE UNIQUE INDEX "user_company_company_id_user_id_key" ON "user_company"("company_id", "user_id");

-- CreateIndex
CREATE INDEX "role_company_id_idx" ON "role"("company_id");

-- CreateIndex
CREATE UNIQUE INDEX "role_company_id_code_key" ON "role"("company_id", "code");

-- CreateIndex
CREATE UNIQUE INDEX "permission_code_key" ON "permission"("code");

-- CreateIndex
CREATE UNIQUE INDEX "user_role_user_company_id_role_id_key" ON "user_role"("user_company_id", "role_id");

-- CreateIndex
CREATE INDEX "session_user_id_idx" ON "session"("user_id");

-- CreateIndex
CREATE UNIQUE INDEX "refresh_token_token_hash_key" ON "refresh_token"("token_hash");

-- CreateIndex
CREATE INDEX "refresh_token_user_id_idx" ON "refresh_token"("user_id");

-- CreateIndex
CREATE INDEX "legal_entity_company_id_idx" ON "legal_entity"("company_id");

-- CreateIndex
CREATE INDEX "branch_company_id_idx" ON "branch"("company_id");

-- CreateIndex
CREATE INDEX "branch_legal_entity_id_idx" ON "branch"("legal_entity_id");

-- CreateIndex
CREATE INDEX "department_company_id_idx" ON "department"("company_id");

-- CreateIndex
CREATE INDEX "designation_company_id_idx" ON "designation"("company_id");

-- CreateIndex
CREATE UNIQUE INDEX "grade_company_id_code_key" ON "grade"("company_id", "code");

-- CreateIndex
CREATE INDEX "holiday_calendar_company_id_idx" ON "holiday_calendar"("company_id");

-- CreateIndex
CREATE INDEX "holiday_calendar_id_idx" ON "holiday"("calendar_id");

-- CreateIndex
CREATE INDEX "employee_company_id_idx" ON "employee"("company_id");

-- CreateIndex
CREATE UNIQUE INDEX "employee_company_id_employee_code_key" ON "employee"("company_id", "employee_code");

-- CreateIndex
CREATE INDEX "employment_company_id_idx" ON "employment"("company_id");

-- CreateIndex
CREATE INDEX "employment_employee_id_idx" ON "employment"("employee_id");

-- CreateIndex
CREATE INDEX "employee_assignment_company_id_idx" ON "employee_assignment"("company_id");

-- CreateIndex
CREATE INDEX "employee_assignment_employee_id_effective_from_idx" ON "employee_assignment"("employee_id", "effective_from");

-- CreateIndex
CREATE INDEX "employee_compensation_company_id_idx" ON "employee_compensation"("company_id");

-- CreateIndex
CREATE INDEX "employee_compensation_employee_id_effective_from_idx" ON "employee_compensation"("employee_id", "effective_from");

-- AddForeignKey
ALTER TABLE "user_company" ADD CONSTRAINT "user_company_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "user_company" ADD CONSTRAINT "user_company_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "user"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "role" ADD CONSTRAINT "role_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "company"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "role_permission" ADD CONSTRAINT "role_permission_role_id_fkey" FOREIGN KEY ("role_id") REFERENCES "role"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "role_permission" ADD CONSTRAINT "role_permission_permission_id_fkey" FOREIGN KEY ("permission_id") REFERENCES "permission"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "user_role" ADD CONSTRAINT "user_role_user_company_id_fkey" FOREIGN KEY ("user_company_id") REFERENCES "user_company"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "user_role" ADD CONSTRAINT "user_role_role_id_fkey" FOREIGN KEY ("role_id") REFERENCES "role"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "session" ADD CONSTRAINT "session_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "user"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "refresh_token" ADD CONSTRAINT "refresh_token_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "user"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "legal_entity" ADD CONSTRAINT "legal_entity_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "branch" ADD CONSTRAINT "branch_legal_entity_id_fkey" FOREIGN KEY ("legal_entity_id") REFERENCES "legal_entity"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "department" ADD CONSTRAINT "department_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "department" ADD CONSTRAINT "department_branch_id_fkey" FOREIGN KEY ("branch_id") REFERENCES "branch"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "designation" ADD CONSTRAINT "designation_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "designation" ADD CONSTRAINT "designation_department_id_fkey" FOREIGN KEY ("department_id") REFERENCES "department"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "grade" ADD CONSTRAINT "grade_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "holiday_calendar" ADD CONSTRAINT "holiday_calendar_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "holiday" ADD CONSTRAINT "holiday_calendar_id_fkey" FOREIGN KEY ("calendar_id") REFERENCES "holiday_calendar"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee" ADD CONSTRAINT "employee_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee" ADD CONSTRAINT "employee_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "user"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employment" ADD CONSTRAINT "employment_company_id_fkey" FOREIGN KEY ("company_id") REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employment" ADD CONSTRAINT "employment_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employment" ADD CONSTRAINT "employment_legal_entity_id_fkey" FOREIGN KEY ("legal_entity_id") REFERENCES "legal_entity"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_assignment" ADD CONSTRAINT "employee_assignment_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_compensation" ADD CONSTRAINT "employee_compensation_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- Doc 03 §3.1 Row-Level Security (see prisma/sql/001_row_level_security.sql)
-- Doc 03 §3.1: Row-Level Security is the backstop for tenant isolation, enabled on every table
-- carrying company_id. The application sets `SET LOCAL app.company_id` at the start of every
-- transaction (see src/core/tenancy) — this policy is what makes a forgotten WHERE clause return
-- zero rows instead of another tenant's data.
--
-- One block per tenant table. Add a new block here whenever a migration adds a table with a
-- company_id column — a CI check should eventually enforce "every new table has RLS enabled"
-- (Doc 03 §3.1) once the migration history exists to lint against.

ALTER TABLE company FORCE ROW LEVEL SECURITY;
-- company itself has no company_id (it IS the tenant root) — no policy needed, RLS not applicable.

DO $$
DECLARE
  tbl text;
BEGIN
  FOREACH tbl IN ARRAY ARRAY[
    'user_company', 'role', 'legal_entity', 'branch', 'department', 'designation', 'grade',
    'holiday_calendar', 'employee', 'employment', 'employee_assignment', 'employee_compensation'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (company_id = current_setting(''app.company_id'', true)::uuid)',
      tbl
    );
  END LOOP;
END $$;

-- Tables one join away from company_id (holiday, role_permission, user_role) rely on their parent's
-- RLS policy plus an application-layer join predicate; they are not given their own RLS policy
-- because they have no company_id column of their own to filter on.

-- Doc 04 §1.2 effective-dating exclusion constraints (see prisma/sql/002_effective_dating_constraints.sql)
-- Doc 04 §1.2: overlapping effective-dated periods must be structurally impossible, not a code
-- convention. Requires the btree_gist extension (see infra/docker/postgres/init/001_extensions.sql).
-- NULL effective_to means "current" — treated as unbounded (infinity) for overlap purposes.

ALTER TABLE employee_assignment
  ADD CONSTRAINT employee_assignment_no_overlap
  EXCLUDE USING gist (
    employee_id WITH =,
    daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
  );

ALTER TABLE employee_compensation
  ADD CONSTRAINT employee_compensation_no_overlap
  EXCLUDE USING gist (
    employee_id WITH =,
    daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
  );

-- Add one block here for every future effective-dated table (employee_statutory, employee_bank,
-- salary_structure assignment, etc. — Doc 04 §5.5/5.6 and the payroll domain) as those land.
