"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { AttendanceStatusBadge } from "@/components/attendance/attendance-status-badge";
import { EmployeeMonthView } from "@/components/attendance/dashboard/employee-month-view";
import { SectionCard } from "@/components/attendance/dashboard/section-card";
import { useSection } from "@/components/attendance/dashboard/use-dashboard-data";
import { PageHeader } from "@/components/common/page-header";
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api/client";
import {
  PRESENCE_LABELS,
  addDays,
  employeeName,
  formatShortDate,
  initials,
  presenceOf,
  type EmployeeLite,
} from "@/lib/attendance/dashboard";
import { businessToday, formatClockTime, formatMinutes } from "@/lib/attendance/format";
import type { AttendanceDay, Punch } from "@/lib/attendance/types";
import { useAuth } from "@/lib/auth/auth-context";
import type { RegularizationRequest } from "@/lib/regularization/types";

function monthBounds(month: string, today: string): { from: string; to: string } {
  const from = `${month}-01`;
  const next = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 1));
  const last = addDays(next.toISOString().slice(0, 10), -1);
  return { from, to: last > today ? today : last };
}

/** HR / manager view of one employee's attendance — identity, today's punches, month summary,
 * calendar, issues and regularizations. Reuses the existing endpoints; every request is
 * DataScope-filtered server-side, so a manager only ever sees their own reportees here. */
export default function EmployeeAttendanceProfilePage() {
  const { employeeId } = useParams<{ employeeId: string }>();
  const { user } = useAuth();
  const timezone = user?.company_timezone ?? "Asia/Kolkata";
  const today = businessToday(timezone);
  const [month, setMonth] = useState(today.slice(0, 7));
  const bounds = monthBounds(month, today);

  // Identity is a nicety — a caller without employee read access still sees the attendance.
  const employee = useSection<EmployeeLite>(
    () => apiClient.get<EmployeeLite>(`/employees/${employeeId}`),
    `emp|${employeeId}`,
    true,
  );
  const days = useSection<AttendanceDay[]>(
    () =>
      apiClient.get<AttendanceDay[]>(
        `/attendance/days?${new URLSearchParams({ employee_id: employeeId, date_from: bounds.from, date_to: bounds.to }).toString()}`,
      ),
    `days|${employeeId}|${bounds.from}|${bounds.to}`,
    true,
  );
  const punches = useSection<Punch[]>(
    () =>
      apiClient.get<Punch[]>(
        `/attendance/punches?${new URLSearchParams({ employee_id: employeeId, date_from: today, date_to: today }).toString()}`,
      ),
    `punches|${employeeId}|${today}`,
    true,
  );
  const regularizations = useSection<RegularizationRequest[]>(
    () => apiClient.get<RegularizationRequest[]>(`/regularizations?${new URLSearchParams({ employee_id: employeeId }).toString()}`),
    `regs|${employeeId}`,
    true,
  );

  const name = employeeName(employee.data ?? undefined, employeeId);
  const todayRow = days.data?.find((d) => d.attendance_date === today) ?? null;

  return (
    <div className="space-y-6">
      <Link href="/app/attendance" className="inline-flex items-center gap-1 text-sm text-foreground-secondary hover:text-foreground">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Attendance
      </Link>

      <div className="flex flex-wrap items-center gap-4">
        <span aria-hidden="true" className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-subtle text-md font-semibold text-primary">
          {initials(name)}
        </span>
        <PageHeader
          title={name}
          description={employee.data?.employee_code ? `Employee ID ${employee.data.employee_code}` : "Attendance profile"}
        />
      </div>

      <SectionCard
        id="att-profile-today"
        title="Today"
        description={formatShortDate(today)}
        status={days.status}
        error={days.error}
        onRetry={days.retry}
      >
        {todayRow ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <AttendanceStatusBadge status={todayRow.attendance_status} />
              <span className="text-sm text-foreground-secondary">{PRESENCE_LABELS[presenceOf(todayRow)]}</span>
            </div>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ["Shift", todayRow.scheduled_start ? `${formatClockTime(todayRow.scheduled_start, timezone)} – ${formatClockTime(todayRow.scheduled_end, timezone)}` : "—"],
                ["Check-in", formatClockTime(todayRow.actual_first_in, timezone)],
                ["Check-out", formatClockTime(todayRow.actual_last_out, timezone)],
                ["Worked", todayRow.actual_first_in ? formatMinutes(todayRow.worked_minutes) : "—"],
              ].map(([label, value]) => (
                <div key={label} className="rounded-md border border-border p-3">
                  <dt className="text-xs text-foreground-muted">{label}</dt>
                  <dd className="mt-1 text-sm font-semibold text-foreground">{value}</dd>
                </div>
              ))}
            </dl>
            {punches.data && punches.data.length > 0 ? (
              <ul className="flex flex-wrap gap-2 text-xs text-foreground-secondary" aria-label="Today's punches">
                {punches.data
                  .slice()
                  .sort((a, b) => a.punch_time.localeCompare(b.punch_time))
                  .map((p) => (
                    <li key={p.id} className="rounded-full border border-border px-2.5 py-1">
                      {p.direction} {formatClockTime(p.punch_time, timezone)}
                    </li>
                  ))}
              </ul>
            ) : null}
            <Link href={`/app/attendance/${todayRow.id}`} className="text-xs text-primary underline">
              Full day detail →
            </Link>
          </div>
        ) : (
          <p className="text-sm text-foreground-secondary">No attendance record for today yet.</p>
        )}
      </SectionCard>

      <SectionCard
        id="att-profile-month"
        title="Month"
        status={days.status}
        error={days.error}
        onRetry={days.retry}
        actions={
          <>
            <label htmlFor="att-profile-month-input" className="sr-only">
              Month
            </label>
            <Input
              id="att-profile-month-input"
              type="month"
              max={today.slice(0, 7)}
              value={month}
              onChange={(e) => e.target.value && setMonth(e.target.value)}
              className="w-44"
            />
          </>
        }
      >
        <EmployeeMonthView
          month={month}
          days={days.data ?? []}
          regularizations={regularizations.data ?? []}
          regularizationNote={
            regularizations.status === "loading"
              ? "Loading requests…"
              : regularizations.status === "error"
                ? "Regularization requests couldn't be loaded."
                : null
          }
        />
      </SectionCard>
    </div>
  );
}
