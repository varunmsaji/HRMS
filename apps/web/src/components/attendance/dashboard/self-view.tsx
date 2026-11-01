"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AttendanceStatusBadge } from "@/components/attendance/attendance-status-badge";
import { EmployeeMonthView } from "@/components/attendance/dashboard/employee-month-view";
import { SectionCard } from "@/components/attendance/dashboard/section-card";
import { useSection } from "@/components/attendance/dashboard/use-dashboard-data";
import { PunchEntryDialog } from "@/components/attendance/punch-entry-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api/client";
import { PRESENCE_LABELS, formatShortDate, hasException, monthStart, presenceOf } from "@/lib/attendance/dashboard";
import { exceptionLabels, minutesSince } from "@/lib/attendance/day-detail";
import { formatClockTime, formatMinutes } from "@/lib/attendance/format";
import type { AttendanceDay } from "@/lib/attendance/types";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { RegularizationRequest } from "@/lib/regularization/types";

interface SelfViewProps {
  employeeId: string;
  today: string;
  timezone: string;
}

/** The employee's own dashboard — never the organisation view. Everything is requested for the
 * caller's own employee id; the backend's data scope would return only their rows regardless. */
export function SelfView({ employeeId, today, timezone }: SelfViewProps) {
  const { can } = usePermissions();
  const [punchOpen, setPunchOpen] = useState(false);
  const month = today.slice(0, 7);

  const days = useSection<AttendanceDay[]>(
    () =>
      apiClient.get<AttendanceDay[]>(
        `/attendance/days?${new URLSearchParams({ employee_id: employeeId, date_from: monthStart(today), date_to: today }).toString()}`,
      ),
    `self-days|${employeeId}|${today}`,
    true,
  );
  const regularizations = useSection<RegularizationRequest[]>(
    () => apiClient.get<RegularizationRequest[]>(`/regularizations?${new URLSearchParams({ employee_id: employeeId }).toString()}`),
    `self-regs|${employeeId}`,
    true,
  );

  const todayRow = days.data?.find((d) => d.attendance_date === today) ?? null;
  // Ticks once a minute while checked in without a check-out, so "time since check-in" stays current.
  const [now, setNow] = useState(() => new Date());
  const checkedInOpen = Boolean(todayRow?.actual_first_in && !todayRow.actual_last_out);
  useEffect(() => {
    if (!checkedInOpen) return;
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, [checkedInOpen]);
  const sinceIn = checkedInOpen ? minutesSince(todayRow?.actual_first_in, now) : null;
  const attention = (days.data ?? [])
    .filter((d) => hasException(d) && d.attendance_date !== today)
    .sort((a, b) => b.attendance_date.localeCompare(a.attendance_date));

  return (
    <div className="space-y-6">
      {attention.length > 0 ? (
        <section
          aria-label="Needs your attention"
          className="rounded-2xl border border-warning-border bg-warning-subtle p-4"
        >
          <p className="text-sm font-semibold text-foreground">
            {attention.length} {attention.length === 1 ? "day needs" : "days need"} your attention this month
          </p>
          <ul className="mt-2 space-y-1.5">
            {attention.slice(0, 4).map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-2 text-sm">
                <Link href={`/app/attendance/${d.id}`} className="font-medium text-foreground hover:underline">
                  {formatShortDate(d.attendance_date)}
                </Link>
                {exceptionLabels(d).map((l) => (
                  <Badge key={l} variant="warning">
                    {l}
                  </Badge>
                ))}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-foreground-secondary">
            Open a day to request a correction.{attention.length > 4 ? ` Showing 4 of ${attention.length}.` : ""}
          </p>
        </section>
      ) : null}

      <SectionCard
        id="att-self-today"
        title="Today"
        description={formatShortDate(today)}
        status={days.status}
        error={days.error}
        onRetry={days.retry}
        actions={
          can("ATTENDANCE.PUNCH") ? (
            <Button type="button" size="sm" onClick={() => setPunchOpen(true)}>
              Record punch
            </Button>
          ) : null
        }
      >
        {todayRow ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <AttendanceStatusBadge status={todayRow.attendance_status} />
              <span className="text-sm text-foreground-secondary">{PRESENCE_LABELS[presenceOf(todayRow)]}</span>
              {todayRow.is_late ? (
                <Badge variant="warning">
                  Late{todayRow.late_minutes > 0 ? ` by ${formatMinutes(todayRow.late_minutes)}` : ""}
                </Badge>
              ) : todayRow.actual_first_in ? (
                <Badge variant="success">On time</Badge>
              ) : null}
              {sinceIn !== null ? (
                <span className="text-sm text-foreground-secondary">
                  In for {formatMinutes(sinceIn)} since check-in
                </span>
              ) : null}
            </div>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ["Shift", todayRow.scheduled_start ? `${formatClockTime(todayRow.scheduled_start, timezone)} – ${formatClockTime(todayRow.scheduled_end, timezone)}` : "—"],
                ["Check-in", formatClockTime(todayRow.actual_first_in, timezone)],
                ["Check-out", formatClockTime(todayRow.actual_last_out, timezone)],
                ["Worked today", todayRow.actual_first_in ? formatMinutes(todayRow.worked_minutes) : "—"],
              ].map(([label, value]) => (
                <div key={label} className="rounded-md border border-border p-3">
                  <dt className="text-xs text-foreground-muted">{label}</dt>
                  <dd className="mt-1 text-sm font-semibold text-foreground">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        ) : (
          <p className="text-sm text-foreground-secondary">
            No attendance record for today yet — it appears once you punch or the daily calculation runs.
          </p>
        )}
      </SectionCard>

      <SectionCard
        id="att-self-month"
        title="This month"
        description="Your attendance for the current month."
        status={days.status}
        error={days.error}
        onRetry={days.retry}
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

      <PunchEntryDialog open={punchOpen} onOpenChange={setPunchOpen} employeeId={employeeId} onRecorded={() => days.retry()} />
    </div>
  );
}
