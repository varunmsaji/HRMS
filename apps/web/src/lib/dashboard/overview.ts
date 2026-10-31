/** Types and pure helpers for the company dashboard's workforce overview
 * (`GET /dashboards/company/attendance-overview`). Every number is the backend's; nothing here
 * re-derives attendance. */

export interface AttendanceBuckets {
  total: number;
  present: number;
  absent: number;
  on_leave: number;
  on_duty: number;
  remote_work: number;
  not_checked_in: number;
  incomplete: number;
  not_expected: number;
  no_record: number;
}

export interface AttendanceDepartmentRow extends AttendanceBuckets {
  department_id: string | null;
  department_name: string;
}

export interface AttendanceOverview extends AttendanceBuckets {
  attendance_date: string;
  timezone: string;
  is_today: boolean;
  generated_at: string;
  expected_employees: number;
  late: number;
  half_day: number;
  half_day_leave: number;
  exceptions: number;
  departments: AttendanceDepartmentRow[];
}

/** The mutually exclusive buckets, in display order. They always sum to `total`. */
export const DISTRIBUTION_BUCKETS = [
  { key: "present", label: "Present", bar: "bg-success" },
  { key: "on_leave", label: "On leave", bar: "bg-on-leave" },
  { key: "on_duty", label: "On duty", bar: "bg-info" },
  { key: "remote_work", label: "Remote", bar: "bg-wfh" },
  { key: "not_checked_in", label: "Not checked in", bar: "bg-border-strong" },
  { key: "absent", label: "Absent", bar: "bg-danger" },
  { key: "incomplete", label: "Incomplete punches", bar: "bg-warning" },
  { key: "not_expected", label: "Weekly off / holiday", bar: "bg-holiday" },
  { key: "no_record", label: "No record yet", bar: "bg-border" },
] as const satisfies ReadonlyArray<{ key: keyof AttendanceBuckets; label: string; bar: string }>;

export type DistributionKey = (typeof DISTRIBUTION_BUCKETS)[number]["key"];

/** Where a headline card drills into. The attendance screen understands `bucket` and a custom
 * single-day range; a card with no matching bucket there opens the screen unfiltered rather than
 * pretending to filter. */
const ATTENDANCE_BUCKET: Partial<Record<keyof AttendanceBuckets | "late" | "exceptions", string>> = {
  present: "PRESENT",
  absent: "ABSENT",
  on_leave: "LEAVE",
  on_duty: "ON_DUTY",
  remote_work: "REMOTE",
  incomplete: "INCOMPLETE",
};

export function attendanceHref(
  key: keyof AttendanceBuckets | "late" | "exceptions",
  attendanceDate: string,
  today: string,
): string {
  const params = new URLSearchParams();
  if (attendanceDate !== today) {
    params.set("range", "custom");
    params.set("from", attendanceDate);
    params.set("to", attendanceDate);
  }
  const bucket = ATTENDANCE_BUCKET[key];
  if (bucket) params.set("bucket", bucket);
  if (key === "late" || key === "not_checked_in") params.set("flag", key);
  const qs = params.toString();
  return qs ? `/app/attendance?${qs}` : "/app/attendance";
}

/** Share of `part` in `whole`, or `null` when there is nothing to divide by. */
export function share(part: number, whole: number): number | null {
  return whole > 0 ? (part / whole) * 100 : null;
}

/** Onboarding cases that need HR (`SUBMITTED`/`UNDER_REVIEW`) vs. the candidate. */
export const ONBOARDING_HR_STATUSES = ["SUBMITTED", "UNDER_REVIEW"] as const;
export const ONBOARDING_CANDIDATE_STATUSES = ["INVITED", "IN_PROGRESS", "CHANGES_REQUESTED"] as const;

export const ONBOARDING_STATUS_LABELS: Record<string, string> = {
  SUBMITTED: "Awaiting HR review",
  UNDER_REVIEW: "Under HR review",
  INVITED: "Invited — awaiting candidate",
  IN_PROGRESS: "Candidate filling details",
  CHANGES_REQUESTED: "Changes requested from candidate",
  VERIFIED: "Verified — ready to activate",
};

/** Reads one allow-listed query value in the browser; `""` on the server or when absent or not
 * allowed. Used to open a list page with a filter already applied from a dashboard link. */
export function initialQueryValue<T extends string>(name: string, allowed: readonly T[]): T | "" {
  if (typeof window === "undefined") return "";
  const value = new URLSearchParams(window.location.search).get(name);
  return value && (allowed as readonly string[]).includes(value) ? (value as T) : "";
}
