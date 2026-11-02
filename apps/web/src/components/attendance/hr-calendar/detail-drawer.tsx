"use client";

import Link from "next/link";

import { AttendanceStatusBadge } from "@/components/attendance/attendance-status-badge";
import { MonthCalendar } from "@/components/attendance/dashboard/month-calendar";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { summarizeMonth, formatShortDate } from "@/lib/attendance/dashboard";
import { summarizeDay } from "@/lib/attendance/day-detail";
import { formatClockTime, formatMinutes } from "@/lib/attendance/format";
import type { CalendarRow } from "@/lib/attendance/hr-calendar";
import type { AttendanceDay } from "@/lib/attendance/types";

export type Selection = { row: CalendarRow; day: AttendanceDay | null } | null;

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <dt className="text-xs text-foreground-muted">{label}</dt>
      <dd className="mt-1 text-sm font-semibold tabular-nums text-foreground">{value}</dd>
    </div>
  );
}

function DayDetails({ day }: { day: AttendanceDay }) {
  const tz = day.timezone;
  const s = summarizeDay(day);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <AttendanceStatusBadge status={day.attendance_status} />
        {s.problems.map((p) => (
          <Badge key={p} variant="warning">
            {p}
          </Badge>
        ))}
        {s.context.map((c) => (
          <Badge key={c} variant="secondary">
            {c}
          </Badge>
        ))}
      </div>
      <p className="text-sm font-medium text-foreground">{s.headline}</p>
      <dl className="grid grid-cols-2 gap-3">
        <Tile label="Scheduled" value={day.scheduled_start && day.scheduled_end ? `${formatClockTime(day.scheduled_start, tz)} – ${formatClockTime(day.scheduled_end, tz)}` : "—"} />
        <Tile label="Worked" value={day.actual_first_in ? formatMinutes(day.worked_minutes) : "—"} />
        <Tile label="First in" value={formatClockTime(day.actual_first_in, tz)} />
        <Tile label="Last out" value={day.actual_last_out ? formatClockTime(day.actual_last_out, tz) : day.missing_punch ? "Missing" : "—"} />
        <Tile label="Late" value={day.is_late ? formatMinutes(day.late_minutes) : "—"} />
        <Tile label="Left early" value={day.is_early_out ? formatMinutes(day.early_departure_minutes) : "—"} />
        <Tile label="Break" value={formatMinutes(day.paid_break_minutes + day.unpaid_break_minutes)} />
        <Tile label="Overtime" value={day.ot_minutes_detected > 0 ? formatMinutes(day.ot_minutes_detected) : "—"} />
      </dl>
      <Link href={`/app/attendance/${day.id}`} className="inline-block text-sm font-medium text-primary hover:underline">
        Open the full day (punch timeline, corrections) →
      </Link>
    </div>
  );
}

function EmployeeMonth({ row, month }: { row: CalendarRow; month: string }) {
  const days = [...row.cells.values()];
  const m = summarizeMonth(days);
  const c = m.counts;
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-3 gap-3">
        <Tile label="Present" value={String(c.PRESENT + c.REMOTE + c.ON_DUTY)} />
        <Tile label="Absent" value={String(c.ABSENT)} />
        <Tile label="On leave" value={String(c.LEAVE)} />
        <Tile label="Late" value={String(m.late)} />
        <Tile label="Missing punch" value={String(m.missingPunch)} />
        <Tile label="Worked" value={formatMinutes(m.workedMinutes)} />
      </dl>
      <MonthCalendar month={month} days={days} />
      <Link href={`/app/attendance/employee/${row.employeeId}`} className="inline-block text-sm font-medium text-primary hover:underline">
        Open this employee&apos;s attendance profile →
      </Link>
    </div>
  );
}

/** Side panel: one day's details when a box was clicked, or the person's whole month when a name was. */
export function DetailDrawer({ selection, month, onClose }: { selection: Selection; month: string; onClose: () => void }) {
  return (
    <Sheet open={selection !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        {selection ? (
          <div className="space-y-5 pt-2">
            <div>
              <SheetTitle>
                {selection.row.name}
                {selection.row.code ? <span className="ml-2 text-sm font-normal text-foreground-muted">{selection.row.code}</span> : null}
              </SheetTitle>
              <SheetDescription>
                {selection.day ? formatShortDate(selection.day.attendance_date) + " " + selection.day.attendance_date.slice(0, 4) : `Whole month · ${month}`}
              </SheetDescription>
            </div>
            {selection.day ? <DayDetails day={selection.day} /> : <EmployeeMonth row={selection.row} month={month} />}
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
