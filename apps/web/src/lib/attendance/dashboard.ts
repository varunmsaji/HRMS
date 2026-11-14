/** Pure view-model logic for the Attendance command-center dashboard.
 *
 * The dashboard's totals (KPIs, distribution, rates, trend, punctuality, weekday pattern,
 * department / branch breakdown) are the backend's, from `GET /v1/attendance/summary` (see
 * `summary.ts`). What remains here classifies and lists individual rows for the per-person views
 * (who's in, needs attention, muster, work hours, reports) — values the backend already computed
 * (`AttendanceDay`, `OvertimeRecord`, `RegularizationRequest`, `AttendancePeriod*`). Nothing
 * recalculates an attendance rule, an overtime amount or a payable day. Percentages are `null`
 * when the denominator is zero. */

import type { DirectoryRow } from "@/lib/employee/directory";
import type { AttendancePeriod, AttendancePeriodSummaryRow } from "@/lib/attendance-period/types";
import { employeeFullName } from "@/lib/employee/names";
import type { OvertimeRecord } from "@/lib/overtime/types";
import type { RegularizationRequest } from "@/lib/regularization/types";

import type { SummaryDay } from "./summary";
import type { AttendanceDay } from "./types";

// ---------------------------------------------------------------------------
// Dates (ISO `YYYY-MM-DD`, pure UTC arithmetic — never the viewer's local zone)
// ---------------------------------------------------------------------------

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function isIsoDate(value: string | null | undefined): value is string {
  return !!value && ISO_DATE.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`));
}

export function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

export function dayDiff(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);
}

export function eachDate(from: string, to: string): string[] {
  const out: string[] = [];
  const span = dayDiff(from, to);
  for (let i = 0; i <= span && i < 400; i += 1) out.push(addDays(from, i));
  return out;
}

/** Monday of the ISO week containing `iso`. */
export function weekStart(iso: string): string {
  const weekday = new Date(`${iso}T00:00:00Z`).getUTCDay(); // 0 = Sunday
  return addDays(iso, -((weekday + 6) % 7));
}

export function monthStart(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

const SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatShortDate(iso: string): string {
  const [, m, d] = iso.split("-").map(Number);
  return `${String(d).padStart(2, "0")} ${SHORT_MONTHS[m - 1]}`;
}

export function formatPct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(1)}%`;
}

/** `null` when the denominator is zero — never a fabricated 0%. */
export function pct(numerator: number, denominator: number): number | null {
  return denominator > 0 ? (numerator / denominator) * 100 : null;
}

// ---------------------------------------------------------------------------
// Range + filters (URL-serialisable so a filtered view can be shared / bookmarked)
// ---------------------------------------------------------------------------

export const RANGE_PRESETS = ["today", "week", "month", "custom"] as const;
export type RangePreset = (typeof RANGE_PRESETS)[number];

export const RANGE_PRESET_LABELS: Record<RangePreset, string> = {
  today: "Today",
  week: "This week",
  month: "This month",
  custom: "Custom",
};

/** Caps a custom range so one request cannot pull an unbounded number of attendance days. */
export const MAX_RANGE_DAYS = 92;
/** The trend/heatmap always show at least this many days ending at the focus date. */
export const MIN_CONTEXT_DAYS = 14;
export const MAX_MUSTER_DAYS = 31;

export interface DateRange {
  from: string;
  to: string;
}

export interface DashboardFilters {
  preset: RangePreset;
  /** Only meaningful when `preset === "custom"`. */
  from: string;
  to: string;
  employeeId: string;
  /** Drill-down by day bucket (chart / KPI click). */
  bucket: DayBucket | "";
  /** Drill-down by exception flag. */
  flag: DayFlag | "";
  /** "range" when the active `bucket`/`flag` drill came from a whole-range Needs Attention item
   * and must filter the entire selected range, not just the focus date. "" (default) is every
   * other drill source (KPI card, status chart, toolbar status select) — all focus-date scoped.
   * Needed because the same `bucket`/`flag` value can be drilled from either source. */
  scope: "" | "range";
  shiftId: string;
  employeeStatus: string;
  /** Scopes the attendance-period panels only — attendance days carry no company. */
  legalEntityId: string;
  /** Department / branch *ids*, or `UNASSIGNED_KEY` for employees with none. The summary matches
   * the assignment in force on each day; the per-person lists match the employee's current one
   * (from the employee directory — attendance days carry neither). */
  department: string;
  branch: string;
}

export const DEFAULT_FILTERS: DashboardFilters = {
  preset: "today",
  from: "",
  to: "",
  employeeId: "",
  bucket: "",
  flag: "",
  scope: "",
  shiftId: "",
  employeeStatus: "",
  legalEntityId: "",
  department: "",
  branch: "",
};

/** The effective [from, to] for the filters. `to` is the *focus date* — headcount sections (KPIs,
 * status chart, Who's In) describe that single date; aggregate sections span the whole range. */
export function resolveRange(filters: DashboardFilters, today: string): DateRange {
  if (filters.preset === "week") return { from: weekStart(today), to: today };
  if (filters.preset === "month") return { from: monthStart(today), to: today };
  if (filters.preset === "custom" && isIsoDate(filters.from) && isIsoDate(filters.to)) {
    let to = filters.to > today ? today : filters.to;
    let from = filters.from;
    if (from > to) from = to;
    if (dayDiff(from, to) >= MAX_RANGE_DAYS) from = addDays(to, -(MAX_RANGE_DAYS - 1));
    if (to < from) to = from;
    return { from, to };
  }
  return { from: today, to: today };
}

/** The span actually fetched: the range, widened to give trends and the heatmap some context. */
export function windowRange(range: DateRange): DateRange {
  const contextFrom = addDays(range.to, -(MIN_CONTEXT_DAYS - 1));
  return { from: range.from < contextFrom ? range.from : contextFrom, to: range.to };
}

type ParamReader = { get(name: string): string | null };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** An id or "unassigned"; anything else (an old link that named the department) is dropped. */
function groupFilterParam(value: string | null): string {
  return value && (value === UNASSIGNED_KEY || UUID.test(value)) ? value : "";
}

export function parseFilters(params: ParamReader): DashboardFilters {
  const preset = params.get("range");
  const bucket = params.get("bucket");
  const flag = params.get("flag");
  return {
    preset: (RANGE_PRESETS as readonly string[]).includes(preset ?? "")
      ? (preset as RangePreset)
      : "today",
    from: params.get("from") ?? "",
    to: params.get("to") ?? "",
    employeeId: params.get("employee") ?? "",
    bucket: (DAY_BUCKETS as readonly string[]).includes(bucket ?? "") ? (bucket as DayBucket) : "",
    flag: (DAY_FLAGS as readonly string[]).includes(flag ?? "") ? (flag as DayFlag) : "",
    scope: params.get("scope") === "range" ? "range" : "",
    shiftId: params.get("shift") ?? "",
    employeeStatus: params.get("estatus") ?? "",
    legalEntityId: params.get("entity") ?? "",
    department: groupFilterParam(params.get("dept")),
    branch: groupFilterParam(params.get("branch")),
  };
}

export function serializeFilters(filters: DashboardFilters): URLSearchParams {
  const out = new URLSearchParams();
  if (filters.preset !== "today") out.set("range", filters.preset);
  if (filters.preset === "custom") {
    if (filters.from) out.set("from", filters.from);
    if (filters.to) out.set("to", filters.to);
  }
  if (filters.employeeId) out.set("employee", filters.employeeId);
  if (filters.bucket) out.set("bucket", filters.bucket);
  if (filters.flag) out.set("flag", filters.flag);
  if (filters.scope) out.set("scope", filters.scope);
  if (filters.shiftId) out.set("shift", filters.shiftId);
  if (filters.employeeStatus) out.set("estatus", filters.employeeStatus);
  if (filters.legalEntityId) out.set("entity", filters.legalEntityId);
  if (filters.department) out.set("dept", filters.department);
  if (filters.branch) out.set("branch", filters.branch);
  return out;
}

export function hasActiveFilters(filters: DashboardFilters): boolean {
  return serializeFilters(filters).toString() !== "";
}

// ---------------------------------------------------------------------------
// Day classification
// ---------------------------------------------------------------------------

/** Mutually exclusive buckets over the backend's `attendance_status` (+ `calendar_day_type` to
 * split `NOT_EXPECTED` into the holiday / weekly-off the chart needs). `WFH` is the only
 * work-mode signal the backend carries, so it is the "Remote" bucket. */
export const DAY_BUCKETS = [
  "PRESENT",
  "REMOTE",
  "ON_DUTY",
  "HALF_DAY",
  "ABSENT",
  "LEAVE",
  "INCOMPLETE",
  "CONFIG_ERROR",
  "HOLIDAY",
  "WEEKLY_OFF",
  "NON_WORKING",
  "NOT_EMPLOYED",
] as const;
export type DayBucket = (typeof DAY_BUCKETS)[number];

export const BUCKET_LABELS: Record<DayBucket, string> = {
  PRESENT: "Present",
  REMOTE: "Remote (WFH)",
  ON_DUTY: "On duty",
  HALF_DAY: "Half day",
  ABSENT: "Absent",
  LEAVE: "On leave",
  INCOMPLETE: "Incomplete",
  CONFIG_ERROR: "Config error",
  HOLIDAY: "Holiday",
  WEEKLY_OFF: "Weekly off",
  NON_WORKING: "Other non-working",
  NOT_EMPLOYED: "Not employed",
};

/** One-glyph code for the muster grid, so status never relies on colour alone. */
export const BUCKET_GLYPHS: Record<DayBucket, string> = {
  PRESENT: "P",
  REMOTE: "R",
  ON_DUTY: "OD",
  HALF_DAY: "½",
  ABSENT: "A",
  LEAVE: "L",
  INCOMPLETE: "!",
  CONFIG_ERROR: "E",
  HOLIDAY: "H",
  WEEKLY_OFF: "W",
  NON_WORKING: "–",
  NOT_EMPLOYED: "·",
};

/** Tailwind token classes (existing design tokens only) per bucket. */
export const BUCKET_TONES: Record<DayBucket, { cell: string; bar: string }> = {
  PRESENT: { cell: "bg-success-subtle text-success", bar: "bg-success" },
  REMOTE: { cell: "bg-wfh-subtle text-wfh", bar: "bg-wfh" },
  ON_DUTY: { cell: "bg-info-subtle text-info", bar: "bg-info" },
  HALF_DAY: { cell: "bg-half-day-subtle text-half-day", bar: "bg-half-day" },
  ABSENT: { cell: "bg-danger-subtle text-danger", bar: "bg-danger" },
  LEAVE: { cell: "bg-on-leave-subtle text-on-leave", bar: "bg-on-leave" },
  INCOMPLETE: { cell: "bg-warning-subtle text-warning", bar: "bg-warning" },
  CONFIG_ERROR: { cell: "bg-danger-subtle text-danger", bar: "bg-danger" },
  HOLIDAY: { cell: "bg-holiday-subtle text-holiday", bar: "bg-holiday" },
  WEEKLY_OFF: { cell: "bg-holiday-subtle text-holiday", bar: "bg-holiday" },
  NON_WORKING: { cell: "bg-muted text-foreground-muted", bar: "bg-border-strong" },
  NOT_EMPLOYED: { cell: "bg-muted text-foreground-disabled", bar: "bg-border" },
};

export function bucketOf(day: AttendanceDay): DayBucket {
  switch (day.attendance_status) {
    case "NOT_JOINED":
    case "EXITED":
      return "NOT_EMPLOYED";
    case "PRESENT":
      return "PRESENT";
    case "WFH":
      return "REMOTE";
    case "ON_DUTY":
      return "ON_DUTY";
    case "HALF_DAY":
      return "HALF_DAY";
    case "ABSENT":
      return "ABSENT";
    case "LEAVE":
      return "LEAVE";
    case "INCOMPLETE":
      return "INCOMPLETE";
    case "CONFIG_ERROR":
      return "CONFIG_ERROR";
    case "NOT_EXPECTED":
      if (day.calendar_day_type === "HOLIDAY") return "HOLIDAY";
      if (day.calendar_day_type === "WEEKLY_OFF") return "WEEKLY_OFF";
      return "NON_WORKING";
    default:
      return "NON_WORKING";
  }
}

const ATTENDING: ReadonlySet<DayBucket> = new Set<DayBucket>(["PRESENT", "REMOTE", "ON_DUTY"]);
/** Buckets where the employee was expected to work — the denominator for rate metrics, so a
 * weekend does not drag "present %" down. */
const NOT_EXPECTED_BUCKETS: ReadonlySet<DayBucket> = new Set<DayBucket>([
  "NOT_EMPLOYED",
  "HOLIDAY",
  "WEEKLY_OFF",
  "NON_WORKING",
]);
/** Buckets where hours are meaningful — attended in some form. */
const WORKED_BUCKETS: ReadonlySet<DayBucket> = new Set<DayBucket>([
  "PRESENT",
  "REMOTE",
  "ON_DUTY",
  "HALF_DAY",
  "INCOMPLETE",
]);

export function isAttending(bucket: DayBucket): boolean {
  return ATTENDING.has(bucket);
}

/** Whether the employee was expected to work — the denominator for every rate. */
export function isExpectedBucket(bucket: DayBucket): boolean {
  return !NOT_EXPECTED_BUCKETS.has(bucket);
}

export const DAY_FLAGS = [
  "late",
  "early_out",
  "missing_punch",
  "overtime",
  "ot_pending",
  "pending_approval",
  "work_on_leave",
  "not_checked_in",
] as const;
export type DayFlag = (typeof DAY_FLAGS)[number];

export const FLAG_LABELS: Record<DayFlag, string> = {
  late: "Late arrivals",
  early_out: "Early departures",
  missing_punch: "Missing punch",
  overtime: "Overtime",
  ot_pending: "Overtime pending approval",
  pending_approval: "Pending approval",
  work_on_leave: "Work on leave",
  not_checked_in: "Not checked in",
};

/** Expected to work but no first-in punch recorded (zero-punch ABSENT, or an INCOMPLETE day with
 * no IN). Before the daily calculation runs there may be no row at all — see `noRecord`. */
export function isNotCheckedIn(day: AttendanceDay): boolean {
  const bucket = bucketOf(day);
  return (bucket === "ABSENT" || bucket === "INCOMPLETE") && !day.actual_first_in;
}

export function isWorkOnLeaveUnresolved(day: AttendanceDay): boolean {
  return day.work_on_leave_flagged && day.work_on_leave_resolution === null;
}

export function matchesFlag(day: AttendanceDay, flag: DayFlag): boolean {
  switch (flag) {
    case "late":
      return day.is_late;
    case "early_out":
      return day.is_early_out;
    case "missing_punch":
      return day.missing_punch;
    case "overtime":
      return day.is_overtime || day.ot_minutes_detected > 0;
    case "ot_pending":
      return day.ot_pending;
    case "pending_approval":
      return day.is_pending_approval;
    case "work_on_leave":
      return isWorkOnLeaveUnresolved(day);
    case "not_checked_in":
      return isNotCheckedIn(day);
  }
}

export function hasException(day: AttendanceDay): boolean {
  return (
    day.missing_punch ||
    day.attendance_status === "CONFIG_ERROR" ||
    day.is_pending_approval ||
    isWorkOnLeaveUnresolved(day)
  );
}

// ---------------------------------------------------------------------------
// Employees
// ---------------------------------------------------------------------------

export interface EmployeeLite {
  id: string;
  first_name: string;
  middle_name?: string | null;
  last_name: string | null;
  display_name?: string | null;
  employee_code: string | null;
  status?: string;
  is_active?: boolean;
  /** Current/most-recent `Employment` spell boundaries (F-1 remediation) — `null`/`undefined`
   * when the employee has no employment row yet (still `PRE_JOINING`). Populated by the bulk
   * `GET /employees` response only (`EmployeeRead.employment_joining_date`/
   * `.employment_last_working_day`); used to decide whether an employee with no attendance row
   * on the focus date is "hasn't checked in yet" (still employed) or "no longer employed", so
   * that decision stops depending on `employee.status`/`is_active`, which the backend does not
   * keep in sync with termination (see `employeesWithoutRecord` below and D-1). */
  employment_joining_date?: string | null;
  employment_last_working_day?: string | null;
}

/** Is `employee` within an employment spell that covers `date` (`YYYY-MM-DD`)? Mirrors the
 * backend's own `joining_date <= date AND (last_working_day IS NULL OR date <= last_working_day)`
 * coverage rule (`apps/api/.../attendance/service.py`'s `_is_employed_on`-equivalent) using the
 * current/most-recent spell's boundaries carried on `EmployeeLite`. An employee with no
 * employment data at all (`employment_joining_date` missing) is treated as not covered — the
 * dashboard's directory only includes employees created via normal lifecycle, so this is
 * effectively never hit for anyone with an attendance row, and conservatively excludes a
 * not-yet-joined employee from "no record yet" rather than guessing they are. */
export function isEmployedOn(employee: EmployeeLite, date: string): boolean {
  const joined = employee.employment_joining_date;
  if (!joined) return false;
  if (joined > date) return false;
  const lastWorkingDay = employee.employment_last_working_day;
  if (lastWorkingDay && lastWorkingDay < date) return false;
  return true;
}

export function employeeName(employee: EmployeeLite | undefined, employeeId: string): string {
  if (!employee) return `Employee ${employeeId.slice(0, 8)}`;
  return employeeFullName(employee) || `Employee ${employeeId.slice(0, 8)}`;
}

export function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0][0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1][0] ?? "") : "";
  return (first + last).toUpperCase();
}

export function indexEmployees(employees: EmployeeLite[]): Map<string, EmployeeLite> {
  const map = new Map<string, EmployeeLite>();
  for (const employee of employees) map.set(employee.id, employee);
  return map;
}

/** The label for employees with no department / branch recorded. */
export const UNASSIGNED = "Unassigned";
/** The department / branch filter value for "no department (branch)". */
export const UNASSIGNED_KEY = "unassigned";

type GroupIds = Pick<DirectoryRow, "department_id" | "branch_id">;

/** The filter value an employee's current department / branch matches. */
function groupFilterKey(row: GroupIds | undefined, key: "department" | "branch"): string {
  return (key === "department" ? row?.department_id : row?.branch_id) ?? UNASSIGNED_KEY;
}

export function groupName(value: string | null | undefined): string {
  return value && value.trim() ? value.trim() : UNASSIGNED;
}

/** Population filters (who is in scope). Drill-down filters (`bucket`/`flag`) are applied
 * separately, so KPIs and charts keep describing the whole population while a list narrows. */
export function applyPopulationFilters(
  days: AttendanceDay[],
  filters: DashboardFilters,
  employeesById: Map<string, EmployeeLite>,
  /** Department / branch per employee. Pass it only once it has loaded — without it the
   * department and branch filters are skipped rather than guessed at. */
  directory?: Map<string, GroupIds>,
): AttendanceDay[] {
  return days.filter((day) => {
    if (directory && filters.department && groupFilterKey(directory.get(day.employee_id), "department") !== filters.department) return false;
    if (directory && filters.branch && groupFilterKey(directory.get(day.employee_id), "branch") !== filters.branch) return false;
    if (filters.employeeId && day.employee_id !== filters.employeeId) return false;
    if (filters.shiftId && day.shift_id !== filters.shiftId) return false;
    if (filters.employeeStatus) {
      const employee = employeesById.get(day.employee_id);
      if (!employee || employee.status !== filters.employeeStatus) return false;
    }
    return true;
  });
}

export function applyDrillFilters(days: AttendanceDay[], filters: DashboardFilters): AttendanceDay[] {
  return days.filter((day) => {
    if (filters.bucket && bucketOf(day) !== filters.bucket) return false;
    if (filters.flag && !matchesFlag(day, filters.flag)) return false;
    return true;
  });
}

export function rowsOn(days: AttendanceDay[], date: string): AttendanceDay[] {
  return days.filter((day) => day.attendance_date === date);
}

export function rowsInRange(days: AttendanceDay[], range: DateRange): AttendanceDay[] {
  return days.filter((day) => day.attendance_date >= range.from && day.attendance_date <= range.to);
}

/** Employees in scope (currently employed on `date`, matching the population filters) with no
 * attendance row on `date` — the daily calculation has not produced one yet (e.g. "hasn't
 * checked in yet today"). Used only for "not checked in".
 *
 * `date` is an explicit parameter — deliberately not re-derived from the system clock in here —
 * so this stays a pure function of its inputs: the same `(rowsOnFocus, employees, filters, date)`
 * always produces the same result, regardless of when it is called (F-1 remediation; previously
 * this silently assumed `date` was always "today" and skipped the employment check entirely,
 * which is what made the same historical date disagree with itself a day apart — see
 * docs/audits/ATTENDANCE_DASHBOARD_F1_REMEDIATION_REPORT.md). Callers should still only invoke
 * this for `date === businessToday()` — for any other date, "no row" already correctly means
 * "not employed that day" (the backend's daily job never produces a row for a day outside an
 * employee's employment spell), so applying this "assume not-yet-calculated" inference to a
 * historical date would be wrong in the opposite direction (see Test B in the remediation
 * report). That gating stays the caller's responsibility (`page.tsx`'s `focusIsToday` check) —
 * this function only answers "who, of the currently-employed population, has no row on `date`".
 */
export function employeesWithoutRecord(
  rowsOnFocus: AttendanceDay[],
  employees: EmployeeLite[],
  filters: DashboardFilters,
  date: string,
  /** Department / branch per employee — the same map the population filter used. */
  directory?: Map<string, GroupIds>,
): EmployeeLite[] {
  const seen = new Set(rowsOnFocus.map((day) => day.employee_id));
  return employees.filter((employee) => {
    if (seen.has(employee.id)) return false;
    if (employee.is_active === false) return false;
    if (!isEmployedOn(employee, date)) return false;
    if (filters.employeeId && employee.id !== filters.employeeId) return false;
    if (filters.employeeStatus && employee.status !== filters.employeeStatus) return false;
    // A shift filter cannot be evaluated for an employee with no row.
    if (filters.shiftId) return false;
    // Without this, everyone the department / branch filter just removed from the list would
    // come straight back as "no record yet".
    if (directory && filters.department && groupFilterKey(directory.get(employee.id), "department") !== filters.department) return false;
    if (directory && filters.branch && groupFilterKey(directory.get(employee.id), "branch") !== filters.branch) return false;
    return true;
  });
}

// ---------------------------------------------------------------------------
// KPIs + distribution
// ---------------------------------------------------------------------------

export interface KpiSet {
  /** Employed rows on the focus date + employees with no record yet. */
  totalEmployees: number;
  noRecord: number;
  present: number;
  remote: number;
  onDuty: number;
  absent: number;
  leave: number;
  halfDay: number;
  holiday: number;
  weeklyOff: number;
  incomplete: number;
  late: number;
  notCheckedIn: number;
  /** Rows with a first-in punch — the denominator for "late". */
  checkedIn: number;
  exceptions: number;
  overtimeEmployees: number;
  overtimeMinutesDetected: number;
  overtimeMinutesApproved: number;
  notEmployed: number;
}

/** Present as the dashboard defines it: office + remote + on-duty (an employee who is working). */
export function presentTotal(kpi: KpiSet): number {
  return kpi.present + kpi.remote + kpi.onDuty;
}

export interface DistributionEntry {
  bucket: DayBucket;
  label: string;
  count: number;
}

// ---------------------------------------------------------------------------
// Trend
// ---------------------------------------------------------------------------

export const TREND_METRICS = [
  "present_pct",
  "absent_pct",
  "leave_pct",
  "late_pct",
  "remote_pct",
  "avg_hours",
] as const;
export type TrendMetric = (typeof TREND_METRICS)[number];

export const TREND_METRIC_LABELS: Record<TrendMetric, string> = {
  present_pct: "Present %",
  absent_pct: "Absent %",
  leave_pct: "Leave %",
  late_pct: "Late %",
  remote_pct: "Remote %",
  avg_hours: "Average hours",
};

export type TrendGranularity = "daily" | "weekly";

export interface TrendPoint {
  key: string;
  label: string;
  /** Percent (0–100) or hours; `null` where the denominator is zero (renders as a gap). */
  value: number | null;
  numerator: number;
  denominator: number;
}

interface DayTally {
  expected: number;
  present: number;
  remote: number;
  absent: number;
  leave: number;
  late: number;
  checkedIn: number;
  workedMinutes: number;
}

function emptyTally(): DayTally {
  return { expected: 0, present: 0, remote: 0, absent: 0, leave: 0, late: 0, checkedIn: 0, workedMinutes: 0 };
}

function tallyInto(tally: DayTally, day: SummaryDay): void {
  tally.expected += day.expected;
  tally.present += day.present;
  tally.remote += day.remote;
  tally.absent += day.absent;
  tally.leave += day.leave;
  tally.late += day.late;
  tally.checkedIn += day.checked_in;
  tally.workedMinutes += day.worked_minutes;
}

function metricOf(tally: DayTally, metric: TrendMetric): Pick<TrendPoint, "value" | "numerator" | "denominator"> {
  switch (metric) {
    case "present_pct":
      return { value: pct(tally.present, tally.expected), numerator: tally.present, denominator: tally.expected };
    case "absent_pct":
      return { value: pct(tally.absent, tally.expected), numerator: tally.absent, denominator: tally.expected };
    case "leave_pct":
      return { value: pct(tally.leave, tally.expected), numerator: tally.leave, denominator: tally.expected };
    case "remote_pct":
      return { value: pct(tally.remote, tally.expected), numerator: tally.remote, denominator: tally.expected };
    case "late_pct":
      return { value: pct(tally.late, tally.checkedIn), numerator: tally.late, denominator: tally.checkedIn };
    case "avg_hours":
      return {
        value: tally.checkedIn > 0 ? tally.workedMinutes / 60 / tally.checkedIn : null,
        numerator: tally.workedMinutes,
        denominator: tally.checkedIn,
      };
  }
}

/** The trend series from the summary's per-day counts. Weekly points add the days' numerators and
 * denominators, so a week's rate is never an average of daily rates. */
export function buildTrend(days: SummaryDay[], range: DateRange, metric: TrendMetric, granularity: TrendGranularity): TrendPoint[] {
  const tallies = new Map<string, DayTally>();
  const keyFor = (date: string) => (granularity === "weekly" ? weekStart(date) : date);
  for (const date of eachDate(range.from, range.to)) {
    const key = keyFor(date);
    if (!tallies.has(key)) tallies.set(key, emptyTally());
  }
  for (const day of days) {
    if (day.date < range.from || day.date > range.to) continue;
    const tally = tallies.get(keyFor(day.date));
    if (tally) tallyInto(tally, day);
  }
  return Array.from(tallies.entries()).map(([key, tally]) => ({
    key,
    label: granularity === "weekly" ? `Wk ${formatShortDate(key)}` : formatShortDate(key),
    ...metricOf(tally, metric),
  }));
}

// ---------------------------------------------------------------------------
// Work hours
// ---------------------------------------------------------------------------

export interface WorkHoursSummary {
  totalMinutes: number;
  checkedInDays: number;
  avgMinutes: number | null;
  /** Sum of the scheduled minutes over days where the employee attended in some form. */
  expectedMinutes: number;
  /** Worked minutes over those same days — the like-for-like figure for `expectedMinutes`. */
  actualOnExpectedMinutes: number;
  deviationMinutes: number;
  /** Shortfall on complete days (both punches) that ended below schedule. */
  underTimeMinutes: number;
  otDetectedMinutes: number;
  otApprovedMinutes: number;
}

export function summarizeWorkHours(rows: AttendanceDay[]): WorkHoursSummary {
  const s: WorkHoursSummary = {
    totalMinutes: 0,
    checkedInDays: 0,
    avgMinutes: null,
    expectedMinutes: 0,
    actualOnExpectedMinutes: 0,
    deviationMinutes: 0,
    underTimeMinutes: 0,
    otDetectedMinutes: 0,
    otApprovedMinutes: 0,
  };
  for (const day of rows) {
    s.otDetectedMinutes += day.ot_minutes_detected;
    s.otApprovedMinutes += day.ot_minutes_approved;
    if (!day.actual_first_in) continue;
    s.totalMinutes += day.worked_minutes;
    s.checkedInDays += 1;
    const scheduled = day.scheduled_minutes ?? 0;
    if (scheduled > 0 && WORKED_BUCKETS.has(bucketOf(day))) {
      s.expectedMinutes += scheduled;
      s.actualOnExpectedMinutes += day.worked_minutes;
      if (day.actual_last_out && day.worked_minutes < scheduled) {
        s.underTimeMinutes += scheduled - day.worked_minutes;
      }
    }
  }
  s.avgMinutes = s.checkedInDays > 0 ? Math.round(s.totalMinutes / s.checkedInDays) : null;
  s.deviationMinutes = s.actualOnExpectedMinutes - s.expectedMinutes;
  return s;
}

export interface DailyHours {
  date: string;
  label: string;
  workedMinutes: number;
  scheduledMinutes: number;
}

export function dailyHours(rows: AttendanceDay[], range: DateRange): DailyHours[] {
  const byDate = new Map<string, DailyHours>();
  for (const date of eachDate(range.from, range.to)) {
    byDate.set(date, { date, label: formatShortDate(date), workedMinutes: 0, scheduledMinutes: 0 });
  }
  for (const day of rows) {
    const entry = byDate.get(day.attendance_date);
    if (!entry || !day.actual_first_in) continue;
    entry.workedMinutes += day.worked_minutes;
    if (WORKED_BUCKETS.has(bucketOf(day))) entry.scheduledMinutes += day.scheduled_minutes ?? 0;
  }
  return Array.from(byDate.values());
}

// ---------------------------------------------------------------------------
// Overtime (from the backend's OvertimeRecord rows)
// ---------------------------------------------------------------------------

export interface OvertimeSummary {
  totalDetectedMinutes: number;
  totalApprovedMinutes: number;
  employees: number;
  avgDetectedPerEmployee: number | null;
  pendingCount: number;
  pendingMinutes: number;
  approvedCount: number;
  rejectedCount: number;
  byDayClass: { dayClass: string; minutes: number }[];
  trend: { date: string; label: string; minutes: number }[];
}

export function summarizeOvertime(records: OvertimeRecord[], range: DateRange): OvertimeSummary {
  const employees = new Set<string>();
  const byClass = new Map<string, number>();
  const byDate = new Map<string, number>();
  for (const date of eachDate(range.from, range.to)) byDate.set(date, 0);
  const s: OvertimeSummary = {
    totalDetectedMinutes: 0,
    totalApprovedMinutes: 0,
    employees: 0,
    avgDetectedPerEmployee: null,
    pendingCount: 0,
    pendingMinutes: 0,
    approvedCount: 0,
    rejectedCount: 0,
    byDayClass: [],
    trend: [],
  };
  for (const record of records) {
    s.totalDetectedMinutes += record.minutes_detected;
    s.totalApprovedMinutes += record.minutes_approved;
    employees.add(record.employee_id);
    if (record.status === "PENDING") {
      s.pendingCount += 1;
      s.pendingMinutes += record.minutes_detected;
    } else if (record.status === "APPROVED" || record.status === "AUTO_APPROVED") {
      s.approvedCount += 1;
    } else if (record.status === "REJECTED") {
      s.rejectedCount += 1;
    }
    const dayClass = record.day_class ?? "UNCLASSIFIED";
    byClass.set(dayClass, (byClass.get(dayClass) ?? 0) + record.minutes_detected);
    if (byDate.has(record.attendance_date)) {
      byDate.set(record.attendance_date, (byDate.get(record.attendance_date) ?? 0) + record.minutes_detected);
    }
  }
  s.employees = employees.size;
  s.avgDetectedPerEmployee = employees.size > 0 ? Math.round(s.totalDetectedMinutes / employees.size) : null;
  s.byDayClass = Array.from(byClass.entries())
    .map(([dayClass, minutes]) => ({ dayClass, minutes }))
    .sort((a, b) => b.minutes - a.minutes);
  s.trend = Array.from(byDate.entries()).map(([date, minutes]) => ({
    date,
    label: formatShortDate(date),
    minutes,
  }));
  return s;
}

// ---------------------------------------------------------------------------
// Needs attention
// ---------------------------------------------------------------------------

export type Severity = "critical" | "high" | "medium" | "low";

export const SEVERITY_ORDER: Record<Severity, number> = { critical: 0, high: 1, medium: 2, low: 3 };

export interface AttentionItem {
  key: string;
  label: string;
  hint: string;
  count: number;
  unit: "employees" | "days" | "requests" | "records" | "periods";
  /** Distinct employees affected, where the source row carries an employee. */
  employees: number | null;
  severity: Severity;
  /** Narrow the on-page list to these rows. */
  flag?: DayFlag;
  bucket?: DayBucket;
  /** Or navigate to the module that owns the workflow. */
  href?: string;
}

export interface AttentionInput {
  rows: AttendanceDay[];
  pendingRegularizations: RegularizationRequest[] | null;
  pendingOvertimeCount: number | null;
  blockedPeriods: AttendancePeriod[] | null;
}

function distinct(rows: AttendanceDay[]): number {
  return new Set(rows.map((day) => day.employee_id)).size;
}

export function buildAttentionItems(input: AttentionInput): AttentionItem[] {
  const { rows } = input;
  const items: AttentionItem[] = [];
  const add = (
    item: Omit<AttentionItem, "count" | "employees"> & { matches: AttendanceDay[] },
  ): void => {
    const { matches, ...rest } = item;
    if (matches.length > 0) items.push({ ...rest, count: matches.length, employees: distinct(matches) });
  };

  add({
    key: "config_error",
    label: "Configuration errors",
    hint: "Days that could not be calculated — shift or policy is missing.",
    unit: "days",
    severity: "critical",
    bucket: "CONFIG_ERROR",
    matches: rows.filter((d) => bucketOf(d) === "CONFIG_ERROR"),
  });
  add({
    key: "missing_punch",
    label: "Missing punches",
    hint: "A day with an IN or OUT punch missing.",
    unit: "days",
    severity: "high",
    flag: "missing_punch",
    matches: rows.filter((d) => d.missing_punch),
  });
  add({
    key: "incomplete",
    label: "Incomplete attendance",
    hint: "Needs manual resolution before the period can close.",
    unit: "days",
    severity: "high",
    bucket: "INCOMPLETE",
    matches: rows.filter((d) => bucketOf(d) === "INCOMPLETE"),
  });
  add({
    key: "work_on_leave",
    label: "Work on approved leave",
    hint: "Punches on a full-day leave awaiting an HR decision.",
    unit: "days",
    severity: "high",
    flag: "work_on_leave",
    matches: rows.filter(isWorkOnLeaveUnresolved),
  });
  add({
    key: "pending_approval",
    label: "Days pending approval",
    hint: "Attendance days waiting on an approval.",
    unit: "days",
    severity: "medium",
    flag: "pending_approval",
    matches: rows.filter((d) => d.is_pending_approval),
  });
  add({
    key: "late",
    label: "Late arrivals",
    hint: "Checked in after the grace window.",
    unit: "days",
    severity: "medium",
    flag: "late",
    matches: rows.filter((d) => d.is_late),
  });
  add({
    key: "early_out",
    label: "Early departures",
    hint: "Checked out before shift end.",
    unit: "days",
    severity: "low",
    flag: "early_out",
    matches: rows.filter((d) => d.is_early_out),
  });

  const regs = input.pendingRegularizations;
  if (regs && regs.length > 0) {
    items.push({
      key: "pending_regularization",
      label: "Regularization pending",
      hint: "Employee correction requests awaiting a decision.",
      count: regs.length,
      unit: "requests",
      employees: new Set(regs.map((r) => r.employee_id)).size,
      severity: "high",
      href: "/app/regularizations",
    });
  }
  if (input.pendingOvertimeCount && input.pendingOvertimeCount > 0) {
    items.push({
      key: "pending_overtime",
      label: "Overtime awaiting approval",
      hint: "Detected overtime not yet approved or rejected.",
      count: input.pendingOvertimeCount,
      unit: "records",
      employees: null,
      severity: "medium",
      href: "/app/overtime",
    });
  }
  const blocked = input.blockedPeriods;
  if (blocked && blocked.length > 0) {
    items.push({
      key: "period_blocked",
      label: "Payroll period blocked",
      hint: "An open attendance period failed validation and cannot be finalized.",
      count: blocked.length,
      unit: "periods",
      employees: null,
      severity: "critical",
      href: blocked.length === 1 ? `/app/attendance-periods/${blocked[0].id}` : "/app/attendance-periods",
    });
  }
  return items.sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] || b.count - a.count);
}

// ---------------------------------------------------------------------------
// Absence insights
// ---------------------------------------------------------------------------

export const REPEAT_ABSENCE_THRESHOLD = 3;

export interface RepeatAbsence {
  employeeId: string;
  absentDays: number;
  leaveDays: number;
}

export function repeatAbsences(rows: AttendanceDay[], threshold = REPEAT_ABSENCE_THRESHOLD): RepeatAbsence[] {
  const byEmployee = new Map<string, RepeatAbsence>();
  for (const day of rows) {
    const bucket = bucketOf(day);
    if (bucket !== "ABSENT" && bucket !== "LEAVE") continue;
    const entry = byEmployee.get(day.employee_id) ?? { employeeId: day.employee_id, absentDays: 0, leaveDays: 0 };
    if (bucket === "ABSENT") entry.absentDays += 1;
    else entry.leaveDays += 1;
    byEmployee.set(day.employee_id, entry);
  }
  return Array.from(byEmployee.values())
    .filter((e) => e.absentDays >= threshold)
    .sort((a, b) => b.absentDays - a.absentDays || b.leaveDays - a.leaveDays);
}

// ---------------------------------------------------------------------------
// Muster / heatmap
// ---------------------------------------------------------------------------

export interface MusterRow {
  employeeId: string;
  name: string;
  code: string | null;
  cells: Map<string, AttendanceDay>;
}

export interface Muster {
  dates: string[];
  rows: MusterRow[];
}

/** Last `MAX_MUSTER_DAYS` days of `range`, so the grid stays readable. */
export function musterDates(range: DateRange): string[] {
  const from = dayDiff(range.from, range.to) >= MAX_MUSTER_DAYS ? addDays(range.to, -(MAX_MUSTER_DAYS - 1)) : range.from;
  return eachDate(from, range.to);
}

export function buildMuster(
  rows: AttendanceDay[],
  dates: string[],
  employeesById: Map<string, EmployeeLite>,
): Muster {
  const visible = new Set(dates);
  const byEmployee = new Map<string, MusterRow>();
  for (const day of rows) {
    if (!visible.has(day.attendance_date)) continue;
    let row = byEmployee.get(day.employee_id);
    if (!row) {
      const employee = employeesById.get(day.employee_id);
      row = {
        employeeId: day.employee_id,
        name: employeeName(employee, day.employee_id),
        code: employee?.employee_code ?? null,
        cells: new Map(),
      };
      byEmployee.set(day.employee_id, row);
    }
    row.cells.set(day.attendance_date, day);
  }
  return { dates, rows: Array.from(byEmployee.values()).sort((a, b) => a.name.localeCompare(b.name)) };
}

/** Month grid for one employee: weeks of 7 (Mon-first) cells, `null` for padding / out-of-range. */
export function monthGrid(month: string, byDate: Map<string, AttendanceDay>): (AttendanceDay | { date: string } | null)[][] {
  const first = `${month}-01`;
  const next = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 1));
  const last = addDays(next.toISOString().slice(0, 10), -1);
  const cells: (AttendanceDay | { date: string } | null)[] = [];
  const lead = (new Date(`${first}T00:00:00Z`).getUTCDay() + 6) % 7;
  for (let i = 0; i < lead; i += 1) cells.push(null);
  for (const date of eachDate(first, last)) cells.push(byDate.get(date) ?? { date });
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks: (AttendanceDay | { date: string } | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

// ---------------------------------------------------------------------------
// Attendance period summary (frozen / live snapshot the backend computed)
// ---------------------------------------------------------------------------

export interface PeriodTotals {
  employees: number;
  frozen: boolean;
  presentDays: number;
  halfDays: number;
  absentDays: number;
  leaveDays: number;
  holidayDays: number;
  weeklyOffDays: number;
  onDutyDays: number | null;
  incompleteDays: number | null;
  notEmployedDays: number | null;
  lopDays: number;
  paidDays: number | null;
  payableDays: number | null;
  otMinutes: number;
  workedMinutes: number;
  lateCount: number;
}

function sumNullable(rows: AttendancePeriodSummaryRow[], pick: (row: AttendancePeriodSummaryRow) => string | null): number | null {
  let seen = false;
  let total = 0;
  for (const row of rows) {
    const value = pick(row);
    if (value === null || value === undefined) continue;
    seen = true;
    total += Number(value);
  }
  return seen ? total : null;
}

export function sumPeriodSummary(rows: AttendancePeriodSummaryRow[]): PeriodTotals {
  const sum = (pick: (row: AttendancePeriodSummaryRow) => string) => sumNullable(rows, pick) ?? 0;
  return {
    employees: rows.length,
    frozen: rows.length > 0 && rows.every((row) => row.frozen),
    presentDays: sum((r) => r.present_days),
    halfDays: sum((r) => r.half_days),
    absentDays: sum((r) => r.absent_days),
    leaveDays: sum((r) => r.leave_days),
    holidayDays: sum((r) => r.holiday_days),
    weeklyOffDays: sum((r) => r.weekly_off_days),
    onDutyDays: sumNullable(rows, (r) => r.on_duty_days),
    incompleteDays: sumNullable(rows, (r) => r.incomplete_days),
    notEmployedDays: sumNullable(rows, (r) => r.not_employed_days),
    lopDays: sum((r) => r.lop_days),
    paidDays: sumNullable(rows, (r) => r.paid_days),
    payableDays: sumNullable(rows, (r) => r.payable_days),
    otMinutes: rows.reduce(
      (acc, r) => acc + r.ot_minutes_normal + r.ot_minutes_weekly_off + r.ot_minutes_holiday + r.ot_minutes_night,
      0,
    ),
    workedMinutes: rows.reduce((acc, r) => acc + r.worked_minutes_total, 0),
    lateCount: rows.reduce((acc, r) => acc + r.late_count, 0),
  };
}

/** The period to summarise by default: the one covering `today`, else the most recent. */
export function pickDefaultPeriod(periods: AttendancePeriod[], today: string): AttendancePeriod | null {
  if (periods.length === 0) return null;
  const covering = periods.find((p) => p.period_start <= today && today <= p.period_end);
  if (covering) return covering;
  return periods.slice().sort((a, b) => b.period_start.localeCompare(a.period_start))[0];
}

// ---------------------------------------------------------------------------
// Presence (derived only from punches + breaks already on the row)
// ---------------------------------------------------------------------------

export type Presence = "WORKING" | "ON_BREAK" | "CHECKED_OUT" | "NOT_CHECKED_IN" | "NONE";

export const PRESENCE_LABELS: Record<Presence, string> = {
  WORKING: "Working",
  ON_BREAK: "On break",
  CHECKED_OUT: "Checked out",
  NOT_CHECKED_IN: "Not checked in",
  NONE: "—",
};

/** The attendance row is a snapshot of the last calculation (run on every punch and by the daily
 * job) — this describes that snapshot, it is not a live presence feed. */
export function presenceOf(day: AttendanceDay): Presence {
  if (!day.actual_first_in) return isNotCheckedIn(day) ? "NOT_CHECKED_IN" : "NONE";
  if (day.actual_last_out) return "CHECKED_OUT";
  return day.breaks.some((b) => b.break_start && !b.break_end) ? "ON_BREAK" : "WORKING";
}

// ---------------------------------------------------------------------------
// Single-employee month summary (employee view + employee profile)
// ---------------------------------------------------------------------------

export interface MonthSummary {
  counts: Record<DayBucket, number>;
  late: number;
  earlyOut: number;
  missingPunch: number;
  pendingApproval: number;
  workOnLeave: number;
  otDetectedMinutes: number;
  otApprovedMinutes: number;
  workedMinutes: number;
  checkedInDays: number;
}

export function summarizeMonth(rows: AttendanceDay[]): MonthSummary {
  const counts = Object.fromEntries(DAY_BUCKETS.map((b) => [b, 0])) as Record<DayBucket, number>;
  const s: MonthSummary = {
    counts,
    late: 0,
    earlyOut: 0,
    missingPunch: 0,
    pendingApproval: 0,
    workOnLeave: 0,
    otDetectedMinutes: 0,
    otApprovedMinutes: 0,
    workedMinutes: 0,
    checkedInDays: 0,
  };
  for (const day of rows) {
    counts[bucketOf(day)] += 1;
    if (day.is_late) s.late += 1;
    if (day.is_early_out) s.earlyOut += 1;
    if (day.missing_punch) s.missingPunch += 1;
    if (day.is_pending_approval) s.pendingApproval += 1;
    if (isWorkOnLeaveUnresolved(day)) s.workOnLeave += 1;
    s.otDetectedMinutes += day.ot_minutes_detected;
    s.otApprovedMinutes += day.ot_minutes_approved;
    if (day.actual_first_in) {
      s.checkedInDays += 1;
      s.workedMinutes += day.worked_minutes;
    }
  }
  return s;
}
