/** Types and pure helpers for `GET /dashboards/company/insights`. Every figure is the backend's. */

export interface HeadcountPoint {
  month: string; // YYYY-MM
  headcount: number;
}

export interface LeaveTypeStat {
  leave_type_id: string;
  name: string;
  code: string | null;
  days: number;
  applications: number;
}

export interface LeaveStatistics {
  scope: "month" | "year";
  period_start: string;
  period_end: string;
  total_days: number;
  by_type: LeaveTypeStat[];
}

export interface UpcomingBirthday {
  employee_id: string;
  name: string;
  designation: string | null;
  photo_url: string | null;
  birthday: string; // YYYY-MM-DD, the next occurrence
  days_until: number;
}

export interface RecentActivity {
  kind: string;
  title: string;
  subject: string | null;
  detail: string | null;
  occurred_at: string;
}

export interface CompanyDashboardInsights {
  today: string;
  headcount_trend: HeadcountPoint[];
  leave_statistics: LeaveStatistics;
  upcoming_birthdays: UpcomingBirthday[];
  recent_activities: RecentActivity[];
}

export function insightsPath(growthMonths: number, leaveScope: "month" | "year"): string {
  return `/dashboards/company/insights?growth_months=${growthMonths}&leave_scope=${leaveScope}`;
}

/** "10 mins ago", "2 hours ago", "3 days ago" — falls back to a date past a month. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const diffMs = now.getTime() - new Date(iso).getTime();
  const mins = Math.max(Math.round(diffMs / 60_000), 0);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min${mins === 1 ? "" : "s"} ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 31) return `${days} day${days === 1 ? "" : "s"} ago`;
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** "Tomorrow" for 1 day out, "Today" for 0, otherwise "15 Sep". */
export function birthdayLabel(b: UpcomingBirthday): string {
  if (b.days_until === 0) return "Today";
  if (b.days_until === 1) return "Tomorrow";
  const [y, m, d] = b.birthday.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

export function monthShort(yyyyMm: string): string {
  const [y, m] = yyyyMm.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" });
}

export function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}
