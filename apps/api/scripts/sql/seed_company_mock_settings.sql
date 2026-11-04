-- Mock configuration data for every Settings screen of the company behind anugrahaaips@gmail.com
-- (technobeala): the policies, calendars, leave rules, payroll rates and assignments the Settings
-- hub exposes, so each screen opens with realistic content instead of an empty state.
--
-- Run as the schema owner (RLS is bypassed by `hrms`, never by `hrms_app`):
--   psql "$MIGRATIONS_DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/seed_company_mock_settings.sql
--
-- Idempotent and re-runnable:
--   * everything it creates is keyed by a fixed code (ATT-STD, LP-CL, WC-IND, ...) or a
--     'mock-settings-seed' reason/note, and is deleted and recreated on each run;
--   * it never touches rows it did not create (the company's own "test" policies, existing shifts,
--     holiday calendars, departments, ...) except to FILL BLANK fields on the company profile, the
--     legal entity and the branch without coordinates - a value somebody typed is never overwritten.
--
-- Screens covered (Settings group -> item):
--   Organisation      Company Profile, Companies (legal entity), Branches (+ geofence coordinates)
--   Attendance & Time Attendance Periods, Work Calendars (+ exceptions), Attendance Policies,
--                     Overtime Policies, Regularization Policies, Workplace Geofences (branch coords)
--   Leave             Leave Types, Leave Policies, Leave Combination Rules, Leave Year,
--                     Statutory Minimums
--   Payroll           Salary Components, Salary Structures, Statutory Rates, Payroll setting
--   Policies          Policy Assignments
-- Not seeded on purpose: Users/roles (needs real credentials), employees, and Shifts / Holiday
-- Calendars / Weekly-Off Patterns / Departments / Designations / Grades (already configured).
--
-- Every figure below is DEMO data. Statutory minimums and rates are unverified placeholders that
-- follow the shape of the real schemes; a compliance owner must enter and verify the real values.

BEGIN;

CREATE TEMP TABLE _co ON COMMIT DROP AS
SELECT DISTINCT uc.company_id, u.id AS user_id
FROM "user" u JOIN user_company uc ON uc.user_id = u.id
WHERE u.email = 'anugrahaaips@gmail.com';

DO $$ BEGIN
  IF (SELECT count(*) FROM _co) <> 1 THEN
    RAISE EXCEPTION 'anugrahaaips@gmail.com is not linked to exactly one company';
  END IF;
  IF (SELECT count(*) FROM legal_entity WHERE company_id = (SELECT company_id FROM _co)) < 1 THEN
    RAISE EXCEPTION 'the company has no legal entity; finish Setup > Company Profile first';
  END IF;
END $$;

-- ---- clean previous run (children before parents) ---------------------------------------------
DELETE FROM policy_assignment
  WHERE company_id = (SELECT company_id FROM _co) AND reason LIKE 'mock-settings-seed%';

DELETE FROM calendar_exception WHERE work_calendar_id IN
  (SELECT id FROM work_calendar WHERE company_id = (SELECT company_id FROM _co)
     AND code IN ('WC-IND', 'WC-5DAY'));
DELETE FROM work_calendar_holiday_calendar WHERE work_calendar_id IN
  (SELECT id FROM work_calendar WHERE company_id = (SELECT company_id FROM _co)
     AND code IN ('WC-IND', 'WC-5DAY'));
DELETE FROM work_calendar
  WHERE company_id = (SELECT company_id FROM _co) AND code IN ('WC-IND', 'WC-5DAY');

DELETE FROM attendance_policy_late_band WHERE policy_version_id IN
  (SELECT v.id FROM attendance_policy_version v JOIN attendance_policy p ON p.id = v.policy_id
   WHERE p.company_id = (SELECT company_id FROM _co) AND p.code IN ('ATT-STD', 'ATT-FLEX', 'ATT-SHIFT'));
DELETE FROM attendance_policy_early_departure_band WHERE policy_version_id IN
  (SELECT v.id FROM attendance_policy_version v JOIN attendance_policy p ON p.id = v.policy_id
   WHERE p.company_id = (SELECT company_id FROM _co) AND p.code IN ('ATT-STD', 'ATT-FLEX', 'ATT-SHIFT'));
DELETE FROM attendance_policy_hour_band WHERE policy_version_id IN
  (SELECT v.id FROM attendance_policy_version v JOIN attendance_policy p ON p.id = v.policy_id
   WHERE p.company_id = (SELECT company_id FROM _co) AND p.code IN ('ATT-STD', 'ATT-FLEX', 'ATT-SHIFT'));
DELETE FROM attendance_policy_version WHERE policy_id IN
  (SELECT id FROM attendance_policy WHERE company_id = (SELECT company_id FROM _co)
     AND code IN ('ATT-STD', 'ATT-FLEX', 'ATT-SHIFT'));
DELETE FROM attendance_policy
  WHERE company_id = (SELECT company_id FROM _co) AND code IN ('ATT-STD', 'ATT-FLEX', 'ATT-SHIFT');

DELETE FROM overtime_policy_rate_row WHERE policy_version_id IN
  (SELECT v.id FROM overtime_policy_version v JOIN overtime_policy p ON p.id = v.policy_id
   WHERE p.company_id = (SELECT company_id FROM _co) AND p.code IN ('OT-STD', 'OT-COMP'));
DELETE FROM overtime_policy_version WHERE policy_id IN
  (SELECT id FROM overtime_policy WHERE company_id = (SELECT company_id FROM _co)
     AND code IN ('OT-STD', 'OT-COMP'));
DELETE FROM overtime_policy
  WHERE company_id = (SELECT company_id FROM _co) AND code IN ('OT-STD', 'OT-COMP');

DELETE FROM regularization_policy_allowed_type WHERE policy_version_id IN
  (SELECT v.id FROM regularization_policy_version v JOIN regularization_policy p ON p.id = v.policy_id
   WHERE p.company_id = (SELECT company_id FROM _co) AND p.code IN ('REG-STD', 'REG-FLEX'));
DELETE FROM regularization_policy_version WHERE policy_id IN
  (SELECT id FROM regularization_policy WHERE company_id = (SELECT company_id FROM _co)
     AND code IN ('REG-STD', 'REG-FLEX'));
DELETE FROM regularization_policy
  WHERE company_id = (SELECT company_id FROM _co) AND code IN ('REG-STD', 'REG-FLEX');

DELETE FROM leave_combination_rule WHERE company_id = (SELECT company_id FROM _co)
  AND reason LIKE 'mock-settings-seed%';
DELETE FROM leave_policy_version WHERE policy_id IN
  (SELECT id FROM leave_policy WHERE company_id = (SELECT company_id FROM _co) AND code LIKE 'LP-%');
DELETE FROM leave_policy WHERE company_id = (SELECT company_id FROM _co) AND code LIKE 'LP-%';
DELETE FROM leave_type WHERE company_id = (SELECT company_id FROM _co)
  AND code IN ('CL', 'SL', 'EL', 'ML', 'PL', 'COMP', 'LOP', 'BRV', 'MRG', 'STD');
DELETE FROM statutory_leave_minimum WHERE company_id = (SELECT company_id FROM _co)
  AND note LIKE 'Mock seed:%';

DELETE FROM statutory_rate WHERE company_id = (SELECT company_id FROM _co)
  AND notes LIKE 'Mock seed:%';

DELETE FROM salary_structure_line WHERE salary_structure_version_id IN
  (SELECT v.id FROM salary_structure_version v JOIN salary_structure s ON s.id = v.salary_structure_id
   WHERE s.company_id = (SELECT company_id FROM _co) AND s.code = 'SENIOR');
DELETE FROM salary_structure_version WHERE salary_structure_id IN
  (SELECT id FROM salary_structure WHERE company_id = (SELECT company_id FROM _co) AND code = 'SENIOR');
DELETE FROM salary_structure WHERE company_id = (SELECT company_id FROM _co) AND code = 'SENIOR';

DELETE FROM attendance_period_action WHERE attendance_period_id IN
  (SELECT id FROM attendance_period WHERE company_id = (SELECT company_id FROM _co)
     AND label LIKE '% (mock)');
DELETE FROM attendance_period
  WHERE company_id = (SELECT company_id FROM _co) AND label LIKE '% (mock)';

-- ============================================================================================
-- ORGANISATION
-- ============================================================================================
-- Company Profile: fill only the blanks.
UPDATE company c SET
  legal_name          = COALESCE(NULLIF(c.legal_name, ''), 'Technobeala Solutions Private Limited'),
  registration_number = COALESCE(NULLIF(c.registration_number, ''), 'U72900KL2020PTC123456'),
  contact_email       = COALESCE(NULLIF(c.contact_email, ''), 'hr@technobeala.example'),
  contact_phone       = COALESCE(NULLIF(c.contact_phone, ''), '+91 484 400 0000'),
  website             = COALESCE(NULLIF(c.website, ''), 'https://technobeala.example'),
  address_line1       = COALESCE(NULLIF(c.address_line1, ''), 'Infopark Phase 1, Kakkanad'),
  address_city        = COALESCE(NULLIF(c.address_city, ''), 'Kochi'),
  address_state       = COALESCE(NULLIF(c.address_state, ''), 'Kerala'),
  address_postal_code = COALESCE(NULLIF(c.address_postal_code, ''), '682042'),
  address_country_code = COALESCE(c.address_country_code, 'IN'),
  business_hours_start = COALESCE(c.business_hours_start, TIME '09:30'),
  business_hours_end   = COALESCE(c.business_hours_end, TIME '18:30')
WHERE c.id = (SELECT company_id FROM _co);

-- Companies (legal entity): statutory registration numbers and the payslip signatory.
UPDATE legal_entity le SET
  tan                   = COALESCE(NULLIF(le.tan, ''), 'KCHT12345A'),
  cin                   = COALESCE(NULLIF(le.cin, ''), 'U72900KL2020PTC123456'),
  pf_code               = COALESCE(NULLIF(le.pf_code, ''), 'KRKOC1234567000'),
  esi_code              = COALESCE(NULLIF(le.esi_code, ''), '65000123450000999'),
  lwf_reg               = COALESCE(NULLIF(le.lwf_reg, ''), 'LWF/KL/2026/0042'),
  signatory_name        = COALESCE(NULLIF(le.signatory_name, ''), 'Rahul Nair'),
  signatory_designation = COALESCE(NULLIF(le.signatory_designation, ''), 'Managing Director')
WHERE le.company_id = (SELECT company_id FROM _co);

-- Branches (also the Workplace Geofences list: a branch with coordinates and a radius).
INSERT INTO branch (company_id, legal_entity_id, name, code, timezone, address_line1, city,
                    state_code, pincode, latitude, longitude, geofence_radius_m, updated_at)
SELECT co.company_id, (SELECT id FROM legal_entity WHERE company_id = co.company_id ORDER BY created_at LIMIT 1),
       v.name, v.code, 'Asia/Kolkata', v.addr, v.city, v.state, v.pin, v.lat, v.lon, v.radius, now()
FROM _co co, (VALUES
  ('Bengaluru HQ',   'BLR', '80 Feet Road, Koramangala',   'Bengaluru', 'KA', '560034', 12.935200, 77.624500, 300),
  ('Mumbai Office',  'MUM', 'Bandra Kurla Complex',        'Mumbai',    'MH', '400051', 19.060700, 72.862600, 300),
  ('Chennai Office', 'CHN', 'Guindy Industrial Estate',    'Chennai',   'TN', '600032', 13.010800, 80.220900, 250)
) AS v(name, code, addr, city, state, pin, lat, lon, radius)
WHERE NOT EXISTS (SELECT 1 FROM branch b WHERE b.company_id = co.company_id AND b.code = v.code);

-- The company's own Kochi branch has no coordinates yet: give it a geofence if it is blank.
UPDATE branch b SET
  address_line1     = COALESCE(NULLIF(b.address_line1, ''), 'Infopark Phase 1, Kakkanad'),
  city              = COALESCE(NULLIF(b.city, ''), 'Kochi'),
  state_code        = COALESCE(NULLIF(b.state_code, ''), 'KL'),
  pincode           = COALESCE(NULLIF(b.pincode, ''), '682042'),
  latitude          = COALESCE(b.latitude, 9.993300),
  longitude         = COALESCE(b.longitude, 76.358500),
  geofence_radius_m = COALESCE(b.geofence_radius_m, 250)
WHERE b.company_id = (SELECT company_id FROM _co) AND b.code = 'BR-001';

-- ============================================================================================
-- ATTENDANCE & TIME
-- ============================================================================================
-- Attendance Periods: two closed months, October validated and ready to close, November open.
WITH ins AS (
  INSERT INTO attendance_period (company_id, legal_entity_id, period_start, period_end, label,
      status, opened_by_user_id, opened_at, last_validated_at, last_validation_status,
      closed_by_user_id, closed_at)
  SELECT co.company_id, le.id, v.ps, v.pe, v.label, v.status, co.user_id, v.opened_at,
         v.validated_at, v.vstatus,
         CASE WHEN v.status = 'CLOSED' THEN co.user_id END, v.closed_at
  FROM _co co
  JOIN LATERAL (SELECT id FROM legal_entity WHERE company_id = co.company_id ORDER BY created_at LIMIT 1) le ON TRUE,
  (VALUES
    (DATE '2026-08-01', DATE '2026-08-31', 'August 2026 (mock)',   'CLOSED',
       TIMESTAMPTZ '2026-08-01 04:00+00', TIMESTAMPTZ '2026-09-02 05:00+00', 'READY', TIMESTAMPTZ '2026-09-02 05:10+00'),
    (DATE '2026-09-01', DATE '2026-09-30', 'September 2026 (mock)', 'CLOSED',
       TIMESTAMPTZ '2026-09-01 04:00+00', TIMESTAMPTZ '2026-10-02 05:00+00', 'READY', TIMESTAMPTZ '2026-10-02 05:10+00'),
    (DATE '2026-10-01', DATE '2026-10-31', 'October 2026 (mock)',   'OPEN',
       TIMESTAMPTZ '2026-10-01 04:00+00', TIMESTAMPTZ '2026-11-03 05:00+00', 'READY', NULL::timestamptz),
    (DATE '2026-11-01', DATE '2026-11-30', 'November 2026 (mock)',  'OPEN',
       TIMESTAMPTZ '2026-11-01 04:00+00', NULL::timestamptz, NULL, NULL::timestamptz)
  ) AS v(ps, pe, label, status, opened_at, validated_at, vstatus, closed_at)
  RETURNING id, status, opened_at, last_validated_at, closed_at, opened_by_user_id, company_id, label
)
INSERT INTO attendance_period_action (company_id, attendance_period_id, action, actor_user_id, comment, created_at)
SELECT company_id, id, a.action, opened_by_user_id, a.comment, a.ts
FROM ins, LATERAL (VALUES
  ('OPENED',    'Period created',        opened_at),
  ('VALIDATED', 'All exceptions cleared', last_validated_at),
  ('CLOSED',    'Locked for payroll',    closed_at)
) AS a(action, comment, ts)
WHERE a.ts IS NOT NULL;

-- Work Calendars: which days are working days / off / holidays, per policy.
INSERT INTO work_calendar (company_id, name, code, description, weekly_off_pattern_id,
                           restricted_holidays_are_off_by_default, is_active)
SELECT co.company_id, v.name, v.code, v.descr,
       (SELECT id FROM weekly_off_pattern w WHERE w.company_id = co.company_id AND w.name = v.pattern LIMIT 1),
       FALSE, TRUE
FROM _co co, (VALUES
  ('India Standard Calendar', 'WC-IND',  'Sunday plus 2nd and 4th Saturday off, with national and Kerala holidays.', '2nd & 4th Saturday + Sunday'),
  ('Five-Day Week Calendar',  'WC-5DAY', 'Saturday and Sunday off, with national and company holidays.',             'Saturday & Sunday')
) AS v(name, code, descr, pattern);

INSERT INTO work_calendar_holiday_calendar (company_id, work_calendar_id, holiday_calendar_id, sort_order)
SELECT wc.company_id, wc.id, hc.id, m.ord
FROM work_calendar wc
JOIN (VALUES
  ('WC-IND',  'India National Holidays 2026', 1),
  ('WC-IND',  'Kerala State Holidays 2026',   2),
  ('WC-5DAY', 'India National Holidays 2026', 1),
  ('WC-5DAY', 'Company Holidays 2026',        2)
) AS m(wc_code, hc_name, ord) ON m.wc_code = wc.code
JOIN holiday_calendar hc ON hc.company_id = wc.company_id AND hc.name = m.hc_name
WHERE wc.company_id = (SELECT company_id FROM _co);

INSERT INTO calendar_exception (company_id, work_calendar_id, exception_date, exception_type, name, reason, is_paid, is_active)
SELECT wc.company_id, wc.id, v.d, v.t, v.name, v.reason, v.paid, TRUE
FROM work_calendar wc
JOIN (VALUES
  ('WC-IND', DATE '2026-11-07', 'SPECIAL_WORKING', 'Release Saturday',      'Quarter-end release; 2nd Saturday worked.', TRUE),
  ('WC-IND', DATE '2026-12-28', 'SHUTDOWN',        'Year-end shutdown',     'Office closed between Christmas and New Year.', TRUE),
  ('WC-IND', DATE '2026-12-29', 'SHUTDOWN',        'Year-end shutdown',     'Office closed between Christmas and New Year.', TRUE),
  ('WC-IND', DATE '2026-12-30', 'SHUTDOWN',        'Year-end shutdown',     'Office closed between Christmas and New Year.', TRUE),
  ('WC-5DAY', DATE '2026-12-28', 'SHUTDOWN',       'Year-end shutdown',     'Office closed between Christmas and New Year.', TRUE)
) AS v(wc_code, d, t, name, reason, paid) ON v.wc_code = wc.code
WHERE wc.company_id = (SELECT company_id FROM _co);

-- Bands helper: late / early-departure / hours-worked bands for a policy version.
CREATE FUNCTION pg_temp._att_bands(p_company uuid, p_version uuid, p_profile text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
  g_in int; g_out int; full_min int; half_min int; late_half int;
BEGIN
  IF p_profile = 'STANDARD' THEN
    g_in := 10; g_out := 15; half_min := 240; full_min := 450; late_half := 120;
  ELSIF p_profile = 'FLEX' THEN
    g_in := 30; g_out := 30; half_min := 180; full_min := 360; late_half := 240;
  ELSE
    g_in := 5;  g_out := 5;  half_min := 300; full_min := 480; late_half := 60;
  END IF;
  INSERT INTO attendance_policy_late_band (company_id, policy_version_id, min_minutes, max_minutes, classification, counts_toward_cap, sort_order) VALUES
    (p_company, p_version, 0,          g_in,      'NONE',     TRUE,  1),
    (p_company, p_version, g_in + 1,   late_half, 'LATE',     TRUE,  2),
    (p_company, p_version, late_half + 1, NULL,   'HALF_DAY', FALSE, 3);
  INSERT INTO attendance_policy_early_departure_band (company_id, policy_version_id, min_minutes, max_minutes, classification, counts_toward_cap, sort_order) VALUES
    (p_company, p_version, 0,          g_out,     'NONE',            TRUE,  1),
    (p_company, p_version, g_out + 1,  late_half, 'EARLY_DEPARTURE', TRUE,  2),
    (p_company, p_version, late_half + 1, NULL,   'HALF_DAY',        FALSE, 3);
  INSERT INTO attendance_policy_hour_band (company_id, policy_version_id, min_minutes, max_minutes, result_status, sort_order) VALUES
    (p_company, p_version, 0,        half_min - 1, 'ABSENT',   1),
    (p_company, p_version, half_min, full_min - 1, 'HALF_DAY', 2),
    (p_company, p_version, full_min, NULL,         'PRESENT',  3);
END $$;

DO $$
DECLARE
  co uuid := (SELECT company_id FROM _co);
  usr uuid := (SELECT user_id FROM _co);
  pol uuid; ver uuid;
BEGIN
  -- Attendance Policies --------------------------------------------------------------------
  -- Standard: v1 (H1) superseded by v2 (current), plus an unpublished draft tightening the rules.
  INSERT INTO attendance_policy (company_id, name, code) VALUES (co, 'Standard Attendance Policy', 'ATT-STD') RETURNING id INTO pol;
  INSERT INTO attendance_policy_version (company_id, policy_id, status, version, effective_from, effective_to,
      grace_in_minutes, grace_out_minutes, missing_punch_behaviour, lates_to_half_day_count,
      incomplete_at_lock_behaviour, geofence_mode, publish_reason, published_at, published_by)
    VALUES (co, pol, 'PUBLISHED', 1, DATE '2026-01-01', DATE '2026-06-30', 15, 15, 'INCOMPLETE', 4,
            'TREAT_ABSENT', 'DISABLED', 'Initial rules', TIMESTAMPTZ '2025-12-20 05:00+00', usr)
    RETURNING id INTO ver;
  PERFORM pg_temp._att_bands(co, ver, 'STANDARD');
  INSERT INTO attendance_policy_version (company_id, policy_id, status, version, effective_from,
      grace_in_minutes, grace_out_minutes, missing_punch_behaviour, lates_to_half_day_count,
      incomplete_at_lock_behaviour, early_departure_requires_approval, geofence_mode,
      geofence_max_accuracy_m, geofence_max_age_seconds, excess_break_behaviour, publish_reason,
      published_at, published_by)
    VALUES (co, pol, 'PUBLISHED', 2, DATE '2026-07-01', 10, 15, 'REQUIRE_REGULARIZATION', 3,
            'TREAT_ABSENT', FALSE, 'OPTIONAL', 100, 60, 'FLAG', 'Tighter grace, geofence recorded',
            TIMESTAMPTZ '2026-06-20 05:00+00', usr)
    RETURNING id INTO ver;
  PERFORM pg_temp._att_bands(co, ver, 'STANDARD');
  INSERT INTO attendance_policy_version (company_id, policy_id, status, version, grace_in_minutes,
      grace_out_minutes, missing_punch_behaviour, lates_to_half_day_count, incomplete_at_lock_behaviour,
      early_departure_requires_approval, geofence_mode)
    VALUES (co, pol, 'DRAFT', 3, 5, 10, 'REQUIRE_REGULARIZATION', 2, 'KEEP_INCOMPLETE', TRUE, 'REQUIRED')
    RETURNING id INTO ver;
  PERFORM pg_temp._att_bands(co, ver, 'SHIFT');

  -- Flexible / field staff: rounding, wide grace, first-in/last-out, no geofence.
  INSERT INTO attendance_policy (company_id, name, code) VALUES (co, 'Flexible and Field Staff Policy', 'ATT-FLEX') RETURNING id INTO pol;
  INSERT INTO attendance_policy_version (company_id, policy_id, status, version, effective_from,
      grace_in_minutes, grace_out_minutes, punch_rounding, rounding_minutes, missing_punch_behaviour,
      auto_close_after_minutes, auto_close_uses_shift_end, half_day_split, multi_punch_mode,
      duplicate_punch_window_seconds, wfh_requires_punch, on_duty_requires_punch, lates_to_half_day_count,
      early_in_allowance_minutes, incomplete_at_lock_behaviour, geofence_mode, publish_reason,
      published_at, published_by)
    VALUES (co, pol, 'PUBLISHED', 1, DATE '2026-01-01', 30, 30, 'NEAREST', 15, 'AUTO_CLOSE', 600, FALSE,
            'BY_MIDPOINT', 'FIRST_IN_LAST_OUT', 120, FALSE, FALSE, 5, 60, 'TREAT_PRESENT', 'DISABLED',
            'Initial rules', TIMESTAMPTZ '2025-12-20 05:00+00', usr)
    RETURNING id INTO ver;
  PERFORM pg_temp._att_bands(co, ver, 'FLEX');

  -- Shift workers: strict geofence, tight grace, breaks need approval, work-on-leave flagged.
  INSERT INTO attendance_policy (company_id, name, code) VALUES (co, 'Shift Workers Policy', 'ATT-SHIFT') RETURNING id INTO pol;
  INSERT INTO attendance_policy_version (company_id, policy_id, status, version, effective_from,
      grace_in_minutes, grace_out_minutes, missing_punch_behaviour, missing_shift_behaviour,
      core_hours_breach_behaviour, early_out_uses_core_end, split_shift_block_mandatory,
      split_shift_missed_block_behaviour, split_shift_allow_hours_compensation, work_on_leave_behaviour,
      excess_break_behaviour, excess_break_days_to_half_day_count, lates_to_half_day_count,
      early_departure_requires_approval, incomplete_at_lock_behaviour, geofence_mode,
      geofence_max_accuracy_m, geofence_max_age_seconds, publish_reason, published_at, published_by)
    VALUES (co, pol, 'PUBLISHED', 1, DATE '2026-01-01', 5, 5, 'REQUIRE_REGULARIZATION', 'ABSENT',
            'HALF_DAY', TRUE, TRUE, 'REQUIRE_REGULARIZATION', TRUE, 'PRESENT_CANCEL_LEAVE_HINT',
            'REQUIRE_APPROVAL', 3, 2, TRUE, 'KEEP_INCOMPLETE', 'REQUIRED', 50, 30, 'Initial rules',
            TIMESTAMPTZ '2025-12-20 05:00+00', usr)
    RETURNING id INTO ver;
  PERFORM pg_temp._att_bands(co, ver, 'SHIFT');

  -- Overtime Policies ------------------------------------------------------------------------
  INSERT INTO overtime_policy (company_id, name, code) VALUES (co, 'Standard Overtime Policy', 'OT-STD') RETURNING id INTO pol;
  INSERT INTO overtime_policy_version (company_id, policy_id, status, version, effective_from, effective_to,
      eligibility, min_ot_minutes, rounding_minutes, rounding_mode, requires_pre_approval,
      requires_post_approval, daily_cap_minutes, monthly_cap_minutes, approval_chain, night_ot_mode,
      publish_reason, published_at, published_by)
    VALUES (co, pol, 'PUBLISHED', 1, DATE '2026-01-01', DATE '2026-06-30', 'SHIFT_FLAG', 30, 15, 'DOWN',
            FALSE, TRUE, 180, 2400, 'MANAGER', 'SHIFT_FLAG', 'Initial rules', TIMESTAMPTZ '2025-12-20 05:00+00', usr)
    RETURNING id INTO ver;
  INSERT INTO overtime_policy_rate_row (company_id, policy_version_id, day_class, classification_code, multiplier_decimal, sort_order) VALUES
    (co, ver, 'NORMAL', 'OT_NORMAL', 1.5, 1), (co, ver, 'WEEKLY_OFF', 'OT_WEEKOFF', 2.0, 2),
    (co, ver, 'HOLIDAY', 'OT_HOLIDAY', 2.0, 3), (co, ver, 'NIGHT', 'OT_NIGHT', 1.75, 4);
  INSERT INTO overtime_policy_version (company_id, policy_id, status, version, effective_from,
      eligibility, min_ot_minutes, rounding_minutes, rounding_mode, requires_pre_approval,
      requires_post_approval, daily_cap_minutes, weekly_cap_minutes, monthly_cap_minutes, approval_chain,
      night_ot_mode, publish_reason, published_at, published_by)
    VALUES (co, pol, 'PUBLISHED', 2, DATE '2026-07-01', 'SHIFT_FLAG', 30, 15, 'DOWN', FALSE, TRUE,
            240, 1200, 3600, 'MANAGER', 'SHIFT_FLAG', 'Caps raised for release season',
            TIMESTAMPTZ '2026-06-20 05:00+00', usr)
    RETURNING id INTO ver;
  INSERT INTO overtime_policy_rate_row (company_id, policy_version_id, day_class, classification_code, multiplier_decimal, sort_order) VALUES
    (co, ver, 'NORMAL', 'OT_NORMAL', 1.5, 1), (co, ver, 'WEEKLY_OFF', 'OT_WEEKOFF', 2.0, 2),
    (co, ver, 'HOLIDAY', 'OT_HOLIDAY', 2.0, 3), (co, ver, 'NIGHT', 'OT_NIGHT', 1.75, 4);

  INSERT INTO overtime_policy (company_id, name, code) VALUES (co, 'Comp-Off Overtime Policy', 'OT-COMP') RETURNING id INTO pol;
  INSERT INTO overtime_policy_version (company_id, policy_id, status, version, effective_from,
      eligibility, min_ot_minutes, rounding_minutes, rounding_mode, requires_pre_approval,
      requires_post_approval, daily_cap_minutes, monthly_cap_minutes, comp_off_instead_of_pay,
      comp_off_expiry_days, comp_off_day_length_minutes, night_ot_mode, night_window_start,
      night_window_end, approval_chain, publish_reason, published_at, published_by)
    VALUES (co, pol, 'PUBLISHED', 1, DATE '2026-01-01', 'GRADE_VIA_ASSIGNMENT', 60, 30, 'NEAREST', TRUE,
            TRUE, 300, 2400, TRUE, 60, 480, 'WINDOW', TIME '22:00', TIME '06:00', 'MANAGER_THEN_HR',
            'Initial rules', TIMESTAMPTZ '2025-12-20 05:00+00', usr)
    RETURNING id INTO ver;
  INSERT INTO overtime_policy_rate_row (company_id, policy_version_id, day_class, classification_code, multiplier_decimal, sort_order) VALUES
    (co, ver, 'NORMAL', 'OT_NORMAL', 1.0, 1), (co, ver, 'WEEKLY_OFF', 'OT_WEEKOFF', 1.0, 2),
    (co, ver, 'HOLIDAY', 'OT_HOLIDAY', 1.0, 3), (co, ver, 'NIGHT', 'OT_NIGHT', 1.0, 4);

  -- Regularization Policies ------------------------------------------------------------------
  INSERT INTO regularization_policy (company_id, name, code) VALUES (co, 'Standard Regularization Policy', 'REG-STD') RETURNING id INTO pol;
  INSERT INTO regularization_policy_version (company_id, policy_id, status, version, effective_from,
      allow_employee_request, allow_manager_request, allow_hr_request, max_backdated_days,
      max_requests_per_month, reason_required, attachment_required, approval_chain, blocked_when_locked,
      publish_reason, published_at, published_by)
    VALUES (co, pol, 'PUBLISHED', 1, DATE '2026-01-01', TRUE, TRUE, TRUE, 30, 5, TRUE, FALSE, 'MANAGER',
            TRUE, 'Initial rules', TIMESTAMPTZ '2025-12-20 05:00+00', usr)
    RETURNING id INTO ver;
  INSERT INTO regularization_policy_allowed_type (company_id, policy_version_id, regularization_type, sort_order)
    SELECT co, ver, t, ord FROM unnest(ARRAY['MISSING_PUNCH', 'WRONG_PUNCH', 'WRONG_STATUS', 'WFH',
      'ON_DUTY', 'FULL_DAY', 'EXCESS_BREAK', 'BREAK_CORRECTION']) WITH ORDINALITY AS u(t, ord);

  INSERT INTO regularization_policy (company_id, name, code) VALUES (co, 'Flexible Regularization Policy', 'REG-FLEX') RETURNING id INTO pol;
  INSERT INTO regularization_policy_version (company_id, policy_id, status, version, effective_from,
      allow_employee_request, allow_manager_request, allow_hr_request, max_backdated_days,
      max_requests_per_month, reason_required, attachment_required, approval_chain,
      auto_approve_within_minutes, blocked_when_locked, publish_reason, published_at, published_by)
    VALUES (co, pol, 'PUBLISHED', 1, DATE '2026-01-01', TRUE, TRUE, TRUE, 60, 10, TRUE, TRUE,
            'MANAGER_THEN_HR', 10, TRUE, 'Initial rules', TIMESTAMPTZ '2025-12-20 05:00+00', usr)
    RETURNING id INTO ver;
  INSERT INTO regularization_policy_allowed_type (company_id, policy_version_id, regularization_type, sort_order)
    SELECT co, ver, t, ord FROM unnest(ARRAY['MISSING_PUNCH', 'WRONG_PUNCH', 'WRONG_SHIFT', 'WRONG_STATUS',
      'WFH', 'ON_DUTY', 'FULL_DAY']) WITH ORDINALITY AS u(t, ord);
END $$;

-- ============================================================================================
-- LEAVE
-- ============================================================================================
-- Leave Year: April to March, matching the company's fiscal year.
UPDATE leave_year_setting SET leave_year_type = 'FINANCIAL', start_month = NULL, start_day = NULL,
  updated_at = now()
WHERE company_id = (SELECT company_id FROM _co);

-- Leave Types
INSERT INTO leave_type (company_id, code, name, is_paid_default, requires_balance, is_comp_off, statutory_category)
SELECT co.company_id, v.code, v.name, v.paid, v.balance, v.comp, v.cat
FROM _co co, (VALUES
  ('CL',   'Casual Leave',       TRUE,  TRUE,  FALSE, NULL),
  ('SL',   'Sick Leave',         TRUE,  TRUE,  FALSE, 'SICK'),
  ('EL',   'Earned Leave',       TRUE,  TRUE,  FALSE, 'EARNED'),
  ('ML',   'Maternity Leave',    TRUE,  TRUE,  FALSE, 'MATERNITY'),
  ('PL',   'Paternity Leave',    TRUE,  TRUE,  FALSE, 'PATERNITY'),
  ('COMP', 'Compensatory Off',   TRUE,  TRUE,  TRUE,  NULL),
  ('LOP',  'Loss of Pay',        FALSE, FALSE, FALSE, NULL),
  ('BRV',  'Bereavement Leave',  TRUE,  TRUE,  FALSE, NULL),
  ('MRG',  'Marriage Leave',     TRUE,  TRUE,  FALSE, NULL),
  ('STD',  'Study Leave',        FALSE, FALSE, FALSE, NULL)
) AS v(code, name, paid, balance, comp, cat);

-- Leave Policies: one policy per type, each with a published version from 2026-01-01.
INSERT INTO leave_policy (company_id, name, code, leave_type_id)
SELECT lt.company_id, lt.name || ' Policy', 'LP-' || lt.code, lt.id
FROM leave_type lt
WHERE lt.company_id = (SELECT company_id FROM _co)
  AND lt.code IN ('CL', 'SL', 'EL', 'ML', 'PL', 'COMP', 'LOP', 'BRV', 'MRG', 'STD');

INSERT INTO leave_policy_version (company_id, policy_id, status, version, effective_from,
    allow_employee_request, allow_manager_request_on_behalf, allow_hr_request_on_behalf,
    max_backdated_days, max_requests_per_month, reason_required, attachment_required, approval_chain,
    half_day_allowed, accrual_frequency, accrual_rate_per_cycle, max_carry_forward_days,
    encashment_allowed, allow_negative_balance, sandwich_rule_enabled, reserve_balance_on_submission,
    pre_delivery_days, post_delivery_days, allowed_during_probation, accrue_during_probation,
    max_encashment_days, min_balance_after_encashment, encashment_frequency,
    encashment_calculation_basis, negative_balance_floor, year_end_action, max_consecutive_days,
    publish_reason, published_at, published_by)
SELECT lp.company_id, lp.id, 'PUBLISHED', 1, DATE '2026-01-01',
       TRUE, TRUE, TRUE, v.backdated, v.per_month, TRUE, v.attach, v.chain,
       v.half, v.freq, v.rate, v.carry,
       v.encash, v.neg, v.sandwich, TRUE,
       v.pre, v.post, v.probation, v.accrue_prob,
       v.enc_max, v.enc_min, v.enc_freq,
       v.enc_basis, v.neg_floor, v.year_end, v.max_consec,
       'Initial rules', TIMESTAMPTZ '2025-12-20 05:00+00', (SELECT user_id FROM _co)
FROM leave_policy lp
JOIN (VALUES
  --  code    backdated per_month attach chain                       half  freq       rate  carry encash neg   sandwich pre   post  probation accrue_prob enc_max enc_min enc_freq   enc_basis    neg_floor year_end        max_consec
  ('LP-CL',  7,  3,    FALSE, 'MANAGER',                  TRUE,  'MONTHLY', 1.0,  0,    FALSE, FALSE, TRUE,    NULL, NULL, TRUE,  TRUE,  NULL, NULL, NULL,     NULL,        NULL,    'LAPSE',         5),
  ('LP-SL',  7,  NULL, TRUE,  'MANAGER',                  TRUE,  'YEARLY',  12.0, 0,    FALSE, FALSE, FALSE,   NULL, NULL, TRUE,  TRUE,  NULL, NULL, NULL,     NULL,        NULL,    'LAPSE',         10),
  ('LP-EL',  30, NULL, FALSE, 'MANAGER_THEN_HR',          TRUE,  'MONTHLY', 1.5,  30,   TRUE,  FALSE, FALSE,   NULL, NULL, FALSE, FALSE, 15,   10,   'YEARLY', 'BASIC',     NULL,    'CARRY_FORWARD', 30),
  ('LP-ML',  200, NULL, TRUE, 'MANAGER_THEN_HR',          FALSE, 'NONE',    NULL, NULL, FALSE, FALSE, FALSE,   56,   84,   TRUE,  TRUE,  NULL, NULL, NULL,     NULL,        NULL,    'LAPSE',         90),
  ('LP-PL',  30, NULL, FALSE, 'MANAGER_THEN_HR',          FALSE, 'YEARLY',  15.0, 0,    FALSE, FALSE, FALSE,   NULL, NULL, TRUE,  TRUE,  NULL, NULL, NULL,     NULL,        NULL,    'LAPSE',         15),
  ('LP-COMP',30, NULL, FALSE, 'MANAGER',                  TRUE,  'NONE',    NULL, 0,    FALSE, FALSE, FALSE,   NULL, NULL, TRUE,  FALSE, NULL, NULL, NULL,     NULL,        NULL,    'LAPSE',         3),
  ('LP-LOP', 7,  NULL, FALSE, 'MANAGER',                  TRUE,  'NONE',    NULL, NULL, FALSE, TRUE,  FALSE,   NULL, NULL, TRUE,  FALSE, NULL, NULL, NULL,     NULL,        30,      'LAPSE',         30),
  ('LP-BRV', 14, NULL, FALSE, 'MANAGER',                  FALSE, 'YEARLY',  3.0,  0,    FALSE, FALSE, FALSE,   NULL, NULL, TRUE,  TRUE,  NULL, NULL, NULL,     NULL,        NULL,    'LAPSE',         3),
  ('LP-MRG', 30, 1,    TRUE,  'MANAGER_THEN_HR',          FALSE, 'YEARLY',  5.0,  0,    FALSE, FALSE, FALSE,   NULL, NULL, FALSE, FALSE, NULL, NULL, NULL,     NULL,        NULL,    'LAPSE',         5),
  ('LP-STD', 0,  1,    TRUE,  'MANAGER_THEN_HOD_THEN_HR', FALSE, 'NONE',    NULL, NULL, FALSE, FALSE, FALSE,   NULL, NULL, FALSE, FALSE, NULL, NULL, NULL,     NULL,        NULL,    'LAPSE',         30)
) AS v(code, backdated, per_month, attach, chain, half, freq, rate, carry, encash, neg, sandwich,
       pre, post, probation, accrue_prob, enc_max, enc_min, enc_freq, enc_basis, neg_floor, year_end, max_consec)
  ON v.code = lp.code
WHERE lp.company_id = (SELECT company_id FROM _co);

-- Leave Combination Rules: pairs that may not overlap on the same dates (all others are allowed).
INSERT INTO leave_combination_rule (company_id, leave_type_id_a, leave_type_id_b, allowed, reason, created_by_user_id)
SELECT co.company_id, a.id, b.id, FALSE, v.reason, co.user_id
FROM _co co
JOIN (VALUES
  ('CL',   'SL',  'mock-settings-seed: casual and sick leave cannot be stacked on the same dates'),
  ('EL',   'ML',  'mock-settings-seed: maternity leave has its own entitlement; earned leave cannot overlap'),
  ('COMP', 'LOP', 'mock-settings-seed: comp-off and loss of pay are mutually exclusive'),
  ('MRG',  'STD', 'mock-settings-seed: marriage and study leave cannot overlap')
) AS v(ca, cb, reason) ON TRUE
JOIN leave_type a ON a.company_id = co.company_id AND a.code = v.ca
JOIN leave_type b ON b.company_id = co.company_id AND b.code = v.cb;

-- Statutory Minimums: the legal floor a leave policy cannot be published below. DEMO figures.
INSERT INTO statutory_leave_minimum (company_id, state_code, establishment_type, leave_category,
    min_days_per_year, note, created_by_user_id)
SELECT co.company_id, v.state, v.est, v.cat, v.days, 'Mock seed: ' || v.note, co.user_id
FROM _co co, (VALUES
  (NULL,  NULL,    'EARNED',    15,  'placeholder national floor - confirm the real figure'),
  (NULL,  NULL,    'SICK',      12,  'placeholder national floor - confirm the real figure'),
  (NULL,  NULL,    'CASUAL',    12,  'placeholder national floor - confirm the real figure'),
  (NULL,  NULL,    'MATERNITY', 182, 'placeholder: 26 weeks'),
  ('KL',  'SHOPS', 'EARNED',    18,  'placeholder Kerala shops and establishments figure'),
  ('KA',  'SHOPS', 'EARNED',    18,  'placeholder Karnataka shops and establishments figure')
) AS v(state, est, cat, days, note);

-- ============================================================================================
-- PAYROLL
-- ============================================================================================
-- Salary Components: add the common allowances and one deduction next to the five system ones.
INSERT INTO salary_component (company_id, code, name, component_type, is_system, is_taxable,
    is_pf_wage, is_esi_wage, is_prorated, show_on_payslip, display_order)
SELECT co.company_id, v.code, v.name, v.type, FALSE, v.taxable, FALSE, v.esi, v.prorated, TRUE, v.ord
FROM _co co, (VALUES
  ('CONVEYANCE',        'Conveyance Allowance',   'EARNING',   TRUE,  TRUE,  TRUE,  40),
  ('MEDICAL',           'Medical Allowance',      'EARNING',   TRUE,  TRUE,  TRUE,  50),
  ('LTA',               'Leave Travel Allowance', 'EARNING',   TRUE,  FALSE, TRUE,  60),
  ('PERFORMANCE_BONUS', 'Performance Bonus',      'EARNING',   TRUE,  FALSE, FALSE, 70),
  ('ADVANCE_RECOVERY',  'Salary Advance Recovery','DEDUCTION', FALSE, FALSE, FALSE, 80)
) AS v(code, name, type, taxable, esi, prorated, ord)
WHERE NOT EXISTS (SELECT 1 FROM salary_component s WHERE s.company_id = co.company_id AND s.code = v.code);

-- Salary Structures: a managerial structure to sit beside Standard and Standard (metro).
WITH s AS (
  INSERT INTO salary_structure (company_id, code, name, description)
  SELECT company_id, 'SENIOR', 'Senior and Managerial', 'Higher basic share with conveyance, medical and LTA.'
  FROM _co RETURNING id, company_id
), v AS (
  INSERT INTO salary_structure_version (company_id, salary_structure_id, version_number, status,
      effective_from, published_at, published_by_user_id)
  SELECT s.company_id, s.id, 1, 'PUBLISHED', DATE '2026-01-01', TIMESTAMPTZ '2025-12-20 05:00+00',
         (SELECT user_id FROM _co)
  FROM s RETURNING id, company_id
)
INSERT INTO salary_structure_line (company_id, salary_structure_version_id, salary_component_id,
    calculation_type, percentage, amount_monthly_minor, base_salary_component_id, max_monthly_minor,
    applies_when, display_order)
SELECT v.company_id, v.id, c.id, l.calc, l.pct, l.amt, b.id, l.cap, l.applies, l.ord
FROM v
JOIN (VALUES
  ('BASIC',             'PERCENTAGE_OF_CTC',       40.0,  NULL::bigint, NULL, NULL::bigint, 'ALWAYS',        10),
  ('HRA',               'PERCENTAGE_OF_COMPONENT', 50.0,  NULL, 'BASIC', NULL, 'ALWAYS',        20),
  ('SPECIAL_ALLOWANCE', 'BALANCING',               NULL,  NULL, NULL,    NULL, 'ALWAYS',        30),
  ('CONVEYANCE',        'FIXED',                   NULL,  160000, NULL,  NULL, 'ALWAYS',        40),
  ('MEDICAL',           'FIXED',                   NULL,  125000, NULL,  NULL, 'ALWAYS',        50),
  ('LTA',               'PERCENTAGE_OF_COMPONENT', 8.33,  NULL, 'BASIC', NULL, 'ALWAYS',        60),
  ('EMPLOYER_PF',       'PERCENTAGE_OF_COMPONENT', 12.0,  NULL, 'BASIC', 180000, 'PF_APPLICABLE', 90),
  ('EMPLOYER_ESI',      'PERCENTAGE_OF_GROSS',     3.25,  NULL, NULL,    NULL, 'ESI_APPLICABLE', 91)
) AS l(code, calc, pct, amt, base_code, cap, applies, ord) ON TRUE
JOIN salary_component c ON c.company_id = v.company_id AND c.code = l.code
LEFT JOIN salary_component b ON b.company_id = v.company_id AND b.code = l.base_code;

-- Statutory Rates (PF, ESI, professional tax, labour welfare fund, TDS). DEMO placeholders, unverified.
INSERT INTO statutory_rate (company_id, scheme, state_code, effective_from, parameters, notes, is_seeded)
SELECT co.company_id, v.scheme, v.state, v.since, v.params::jsonb, 'Mock seed: ' || v.note, FALSE
FROM _co co, (VALUES
  ('PF',  NULL, DATE '2014-09-01',
   '{"employee_percent":"12","employer_percent":"12","eps_percent":"8.33","wage_ceiling_minor":1500000,"edli_percent":"0.5","admin_percent":"0.5","eps_age_limit":58}',
   'EPF 12% / 12%, EPS 8.33% on wages up to Rs 15,000. Verify before use.'),
  ('ESI', NULL, DATE '2019-07-01',
   '{"employee_percent":"0.75","employer_percent":"3.25","wage_ceiling_minor":2100000,"employee_exempt_daily_wage_minor":17600}',
   'ESI 0.75% / 3.25%, wage ceiling Rs 21,000. Verify before use.'),
  ('PT',  'KA', DATE '2025-04-01',
   '{"slabs":[{"min_minor":0,"max_minor":2499999,"amount_minor":0},{"min_minor":2500000,"max_minor":null,"amount_minor":20000,"month_amounts":{"2":30000}}]}',
   'Karnataka professional tax slabs. Verify before use.'),
  ('PT',  'MH', DATE '2023-07-01',
   '{"slabs":[{"min_minor":0,"max_minor":750000,"amount_minor":0},{"min_minor":750001,"max_minor":1000000,"amount_minor":17500},{"min_minor":1000001,"max_minor":null,"amount_minor":20000,"month_amounts":{"2":30000}}]}',
   'Maharashtra professional tax slabs. Verify before use.'),
  ('PT',  'KL', DATE '2024-04-01',
   '{"slabs":[{"min_minor":0,"max_minor":1199999,"amount_minor":0},{"min_minor":1200000,"max_minor":1749999,"amount_minor":12000},{"min_minor":1750000,"max_minor":null,"amount_minor":20000}]}',
   'Kerala professional tax slabs (placeholder). Verify before use.'),
  ('LWF', 'KA', DATE '2025-01-01',
   '{"months":[12],"slabs":[{"min_minor":0,"max_minor":null,"employee_minor":2000,"employer_minor":4000}]}',
   'Karnataka labour welfare fund, paid in December (placeholder). Verify before use.'),
  ('TDS', NULL, DATE '2025-04-01',
   '{"regime":"NEW","standard_deduction_minor":7500000,"rebate_taxable_income_limit_minor":120000000,"cess_percent":"4","surcharge_warning_income_minor":500000000,"slabs":[{"min_minor":0,"max_minor":40000000,"percent":"0"},{"min_minor":40000000,"max_minor":80000000,"percent":"5"},{"min_minor":80000000,"max_minor":120000000,"percent":"10"},{"min_minor":120000000,"max_minor":160000000,"percent":"15"},{"min_minor":160000000,"max_minor":200000000,"percent":"20"},{"min_minor":200000000,"max_minor":240000000,"percent":"25"},{"min_minor":240000000,"max_minor":null,"percent":"30"}]}',
   'New tax regime FY 2025-26 slabs. Verify before use.')
) AS v(scheme, state, since, params, note);

-- Payroll setting: how far a pay run may drift from the previous month before it is flagged.
INSERT INTO payroll_setting (company_id, variance_threshold_percent)
SELECT company_id, 12 FROM _co
ON CONFLICT (company_id) DO NOTHING;

-- ============================================================================================
-- POLICIES: assignments (the most specific scope wins; company is the safety net)
-- ============================================================================================
INSERT INTO policy_assignment (company_id, policy_kind, policy_id, leave_type_id, scope_type, scope_id,
                               effective_from, priority, reason, is_active)
SELECT co.company_id, v.kind, p.id, p.leave_type_id, v.scope, sc.id, DATE '2026-01-01', 0,
       'mock-settings-seed: ' || v.why, TRUE
FROM _co co
JOIN (VALUES
  -- company-wide defaults
  ('WORK_CALENDAR',         'WC-IND',    'COMPANY',    NULL,             'company default calendar'),
  ('WEEKLY_OFF',            'Sunday Only', 'COMPANY',  NULL,             'company default weekly off'),
  ('ATTENDANCE_POLICY',     'ATT-STD',   'COMPANY',    NULL,             'company default attendance rules'),
  ('OVERTIME_POLICY',       'OT-STD',    'COMPANY',    NULL,             'company default overtime'),
  ('REGULARIZATION_POLICY', 'REG-STD',   'COMPANY',    NULL,             'company default regularization'),
  -- narrower overrides
  ('ATTENDANCE_POLICY',     'ATT-FLEX',  'DEPARTMENT', 'Sales',          'field sales runs on flexible attendance'),
  ('REGULARIZATION_POLICY', 'REG-FLEX',  'DEPARTMENT', 'Sales',          'field sales gets flexible corrections'),
  ('ATTENDANCE_POLICY',     'ATT-SHIFT', 'DEPARTMENT', 'Operations',     'operations is shift based'),
  ('OVERTIME_POLICY',       'OT-COMP',   'DEPARTMENT', 'Operations',     'operations is paid in comp-off'),
  ('WORK_CALENDAR',         'WC-5DAY',   'BRANCH',     'Mumbai Office',  'Mumbai follows a five-day week')
) AS v(kind, policy_ref, scope, scope_name, why) ON TRUE
JOIN LATERAL (
  SELECT id, NULL::uuid AS leave_type_id FROM work_calendar        WHERE v.kind = 'WORK_CALENDAR'         AND company_id = co.company_id AND code = v.policy_ref
  UNION ALL
  SELECT id, NULL FROM weekly_off_pattern WHERE v.kind = 'WEEKLY_OFF'            AND company_id = co.company_id AND name = v.policy_ref
  UNION ALL
  SELECT id, NULL FROM attendance_policy     WHERE v.kind = 'ATTENDANCE_POLICY'     AND company_id = co.company_id AND code = v.policy_ref
  UNION ALL
  SELECT id, NULL FROM overtime_policy       WHERE v.kind = 'OVERTIME_POLICY'       AND company_id = co.company_id AND code = v.policy_ref
  UNION ALL
  SELECT id, NULL FROM regularization_policy WHERE v.kind = 'REGULARIZATION_POLICY' AND company_id = co.company_id AND code = v.policy_ref
) p ON TRUE
LEFT JOIN LATERAL (
  SELECT id FROM department WHERE v.scope = 'DEPARTMENT' AND company_id = co.company_id AND name = v.scope_name
  UNION ALL
  SELECT id FROM branch     WHERE v.scope = 'BRANCH'     AND company_id = co.company_id AND name = v.scope_name
) sc ON TRUE
WHERE v.scope = 'COMPANY' OR sc.id IS NOT NULL;

-- One company-wide leave policy per leave type (the leave type is part of the assignment).
INSERT INTO policy_assignment (company_id, policy_kind, policy_id, leave_type_id, scope_type, scope_id,
                               effective_from, priority, reason, is_active)
SELECT lp.company_id, 'LEAVE_POLICY', lp.id, lp.leave_type_id, 'COMPANY', NULL, DATE '2026-01-01', 0,
       'mock-settings-seed: company default for ' || lp.name, TRUE
FROM leave_policy lp
WHERE lp.company_id = (SELECT company_id FROM _co) AND lp.code LIKE 'LP-%';

COMMIT;
