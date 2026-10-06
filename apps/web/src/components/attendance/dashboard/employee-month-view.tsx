import Link from "next/link";

import { AttendanceStatusBadge } from "@/components/attendance/attendance-status-badge";
import { MonthCalendar } from "@/components/attendance/dashboard/month-calendar";
import { RegularizationStatusBadge } from "@/components/regularization/regularization-status-badge";
import { Badge } from "@/components/ui/badge";
import {
  formatShortDate,
  hasException,
  summarizeMonth,
} from "@/lib/attendance/dashboard";
import { formatMinutes } from "@/lib/attendance/format";
import type { AttendanceDay } from "@/lib/attendance/types";
import { REGULARIZATION_TYPE_LABELS, type RegularizationRequest } from "@/lib/regularization/types";

interface EmployeeMonthViewProps {
  month: string;
  days: AttendanceDay[];
  regularizations: RegularizationRequest[];
  /** `null` while the regularization list is loading or unavailable. */
  regularizationNote?: string | null;
}

function problemLabels(day: AttendanceDay): string[] {
  const labels: string[] = [];
  if (day.missing_punch) labels.push("Missing punch");
  if (day.attendance_status === "CONFIG_ERROR") labels.push("Config error");
  if (day.attendance_status === "INCOMPLETE") labels.push("Incomplete");
  if (day.is_pending_approval) labels.push("Pending approval");
  if (day.work_on_leave_flagged && day.work_on_leave_resolution === null) labels.push("Work on leave");
  return labels;
}

/** The month-level story for one employee — shared by the employee's own dashboard and the HR
 * employee-attendance profile. Everything is read off the backend's day rows. */
export function EmployeeMonthView({ month, days, regularizations, regularizationNote }: EmployeeMonthViewProps) {
  const summary = summarizeMonth(days);
  const c = summary.counts;
  const issues = days.filter(hasException).sort((a, b) => b.attendance_date.localeCompare(a.attendance_date));
  const stats: [string, string][] = [
    ["Present", String(c.PRESENT + c.REMOTE + c.ON_DUTY)],
    ["Half days", String(c.HALF_DAY)],
    ["Absent", String(c.ABSENT)],
    ["On leave", String(c.LEAVE)],
    ["Holidays / weekly offs", String(c.HOLIDAY + c.WEEKLY_OFF)],
    ["Late arrivals", String(summary.late)],
    ["Early departures", String(summary.earlyOut)],
    ["Worked", formatMinutes(summary.workedMinutes)],
    ["Overtime", summary.otDetectedMinutes > 0 ? `${formatMinutes(summary.otDetectedMinutes)} (${formatMinutes(summary.otApprovedMinutes)} approved)` : "None"],
  ];
  return (
    <div className="space-y-6">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-md border border-border p-3">
            <dt className="text-xs text-foreground-muted">{label}</dt>
            <dd className="mt-1 text-lg font-semibold tabular-nums text-foreground">{value}</dd>
          </div>
        ))}
      </dl>

      <section aria-labelledby="emp-cal-heading" className="space-y-2">
        <h3 id="emp-cal-heading" className="text-sm font-semibold text-foreground">Calendar</h3>
        <MonthCalendar month={month} days={days} />
      </section>

      <section aria-labelledby="emp-issues-heading" className="space-y-2">
        <h3 id="emp-issues-heading" className="text-sm font-semibold text-foreground">Attendance issues</h3>
        {issues.length === 0 ? (
          <p className="text-sm text-foreground-secondary">No attendance issues this month.</p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {issues.map((day) => (
              <li key={day.id}>
                <Link href={`/app/attendance/${day.id}`} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm hover:bg-accent">
                  <span className="w-16 font-medium text-foreground">{formatShortDate(day.attendance_date)}</span>
                  <AttendanceStatusBadge status={day.attendance_status} />
                  {problemLabels(day).map((label) => (
                    <Badge key={label} variant="warning">{label}</Badge>
                  ))}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="emp-reg-heading" className="space-y-2">
        <div className="flex items-center justify-between">
          <h3 id="emp-reg-heading" className="text-sm font-semibold text-foreground">Regularization requests</h3>
          <Link href="/app/regularizations" className="text-xs text-primary underline">All requests →</Link>
        </div>
        {regularizationNote ? (
          <p className="text-sm text-foreground-secondary">{regularizationNote}</p>
        ) : regularizations.length === 0 ? (
          <p className="text-sm text-foreground-secondary">No regularization requests.</p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {regularizations.slice(0, 8).map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                <span className="w-16 font-medium text-foreground">{formatShortDate(r.attendance_date)}</span>
                <span className="flex-1 text-foreground-secondary">{REGULARIZATION_TYPE_LABELS[r.request_type] ?? r.request_type}</span>
                <RegularizationStatusBadge status={r.status} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
