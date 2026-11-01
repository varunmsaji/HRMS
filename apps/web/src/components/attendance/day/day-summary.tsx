"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";

import { AttendanceStatusBadge } from "@/components/attendance/attendance-status-badge";
import { Badge } from "@/components/ui/badge";
import { summarizeDay } from "@/lib/attendance/day-detail";
import { formatClockTime, formatMinutes } from "@/lib/attendance/format";
import type { AttendanceDay } from "@/lib/attendance/types";
import { cn } from "@/lib/utils";

interface Props {
  day: AttendanceDay;
  employeeName: string | null;
  employeeCode: string | null;
  shiftName: string | null;
  /** Neighbouring day ids for this employee (null = none recorded / not loaded). */
  prevDayId: string | null;
  nextDayId: string | null;
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <dt className="text-xs text-foreground-muted">{label}</dt>
      <dd className={cn("mt-1 text-lg font-semibold tabular-nums text-foreground", tone)}>{value}</dd>
    </div>
  );
}

function NavButton({ id, direction }: { id: string | null; direction: "prev" | "next" }) {
  const Icon = direction === "prev" ? ChevronLeft : ChevronRight;
  const label = direction === "prev" ? "Previous day" : "Next day";
  const cls = "inline-flex h-9 w-9 items-center justify-center rounded-md border border-border";
  return id ? (
    <Link href={`/app/attendance/${id}`} aria-label={label} className={cn(cls, "bg-surface hover:bg-muted")}>
      <Icon className="h-4 w-4" aria-hidden="true" />
    </Link>
  ) : (
    <span aria-label={`${label} (no record)`} aria-disabled="true" className={cn(cls, "cursor-not-allowed text-foreground-disabled")}>
      <Icon className="h-4 w-4" aria-hidden="true" />
    </span>
  );
}

/** What happened on this day, in plain words, with the key numbers and day-to-day navigation. */
export function DaySummaryCard({ day, employeeName, employeeCode, shiftName, prevDayId, nextDayId }: Props) {
  const summary = summarizeDay(day);
  const tz = day.timezone;
  return (
    <section aria-label="Day summary" className="rounded-2xl border border-border bg-surface p-6 shadow-elevation-1">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {employeeName ? (
            <p className="text-sm text-foreground-secondary">
              <Link href={`/app/attendance/employee/${day.employee_id}`} className="font-medium text-foreground hover:underline">
                {employeeName}
              </Link>
              {employeeCode ? <span className="text-foreground-muted"> · {employeeCode}</span> : null}
              {shiftName ? <span className="text-foreground-muted"> · {shiftName}</span> : null}
            </p>
          ) : null}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <AttendanceStatusBadge status={day.attendance_status} />
            {summary.problems.map((p) => (
              <Badge key={p} variant="warning">
                {p}
              </Badge>
            ))}
            {summary.context.map((c) => (
              <Badge key={c} variant="secondary">
                {c}
              </Badge>
            ))}
          </div>
          <p className="mt-3 text-base font-medium text-foreground">{summary.headline}</p>
        </div>
        <div className="flex items-center gap-2">
          <NavButton id={prevDayId} direction="prev" />
          <NavButton id={nextDayId} direction="next" />
        </div>
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile label="Scheduled" value={day.scheduled_start && day.scheduled_end ? `${formatClockTime(day.scheduled_start, tz)} – ${formatClockTime(day.scheduled_end, tz)}` : "—"} />
        <Tile label="First in" value={formatClockTime(day.actual_first_in, tz)} tone={day.is_late ? "text-warning" : undefined} />
        <Tile
          label="Last out"
          value={day.actual_last_out ? formatClockTime(day.actual_last_out, tz) : day.missing_punch ? "Missing" : "—"}
          tone={day.missing_punch && !day.actual_last_out ? "text-danger" : day.is_early_out ? "text-warning" : undefined}
        />
        <Tile label="Worked" value={day.actual_first_in ? formatMinutes(day.worked_minutes) : "—"} />
      </dl>
    </section>
  );
}
