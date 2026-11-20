import {
  CalendarCheck,
  CalendarOff,
  Clock,
  Hourglass,
  LogOut,
  Plane,
  Timer,
  TrendingUp,
  UserX,
} from "lucide-react";
import Link from "next/link";

import { AttendanceStatusBadge } from "@/components/attendance/attendance-status-badge";
import { StatTile, type StatTileProps } from "@/components/attendance/stat-tile";
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
  const stats: StatTileProps[] = [
    { label: "Present", value: String(c.PRESENT + c.REMOTE + c.ON_DUTY), icon: CalendarCheck, accent: "success" },
    { label: "Half days", value: String(c.HALF_DAY), icon: Hourglass, accent: "warning" },
    { label: "Absent", value: String(c.ABSENT), icon: UserX, accent: "danger", tone: c.ABSENT > 0 ? "text-danger" : undefined },
    { label: "On leave", value: String(c.LEAVE), icon: Plane, accent: "leave" },
    { label: "Holidays / weekly offs", value: String(c.HOLIDAY + c.WEEKLY_OFF), icon: CalendarOff, accent: "holiday" },
    { label: "Late arrivals", value: String(summary.late), icon: Clock, accent: "warning", tone: summary.late > 0 ? "text-warning" : undefined },
    { label: "Early departures", value: String(summary.earlyOut), icon: LogOut, accent: "warning", tone: summary.earlyOut > 0 ? "text-warning" : undefined },
    { label: "Worked", value: formatMinutes(summary.workedMinutes), icon: Timer, accent: "info" },
    {
      label: "Overtime",
      value: summary.otDetectedMinutes > 0 ? formatMinutes(summary.otDetectedMinutes) : "None",
      hint: summary.otDetectedMinutes > 0 ? `${formatMinutes(summary.otApprovedMinutes)} approved` : undefined,
      icon: TrendingUp,
      accent: "leave",
    },
  ];
  return (
    <div className="space-y-6">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        {stats.map((stat) => (
          <StatTile key={stat.label} {...stat} />
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
                  <AttendanceStatusBadge status={day.attendance_status} display={day.display} />
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
