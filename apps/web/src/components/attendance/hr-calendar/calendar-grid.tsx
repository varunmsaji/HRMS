"use client";

import {
  BUCKET_GLYPHS,
  BUCKET_LABELS,
  BUCKET_TONES,
  DAY_BUCKETS,
  bucketOf,
  formatShortDate,
} from "@/lib/attendance/dashboard";
import { formatClockTime, formatMinutes } from "@/lib/attendance/format";
import type { CalendarRow } from "@/lib/attendance/hr-calendar";
import type { AttendanceDay } from "@/lib/attendance/types";
import { cn } from "@/lib/utils";

interface Props {
  rows: CalendarRow[];
  dates: string[];
  today: string;
  onPickDay: (row: CalendarRow, day: AttendanceDay) => void;
  onPickEmployee: (row: CalendarRow) => void;
}

function tooltip(row: CalendarRow, day: AttendanceDay): string {
  const label = BUCKET_LABELS[bucketOf(day)];
  const times = day.actual_first_in
    ? ` — in ${formatClockTime(day.actual_first_in, day.timezone)}${day.actual_last_out ? `, out ${formatClockTime(day.actual_last_out, day.timezone)}` : ", no punch-out"}, ${formatMinutes(day.worked_minutes)}`
    : "";
  return `${row.name}, ${formatShortDate(day.attendance_date)}: ${label}${times}`;
}

/** Every employee for a month: names down the side, days across, each box that day's status.
 * Click a box for the day's details, or a name for that person's whole month. */
export function CalendarGrid({ rows, dates, today, onPickDay, onPickEmployee }: Props) {
  const used = new Set<string>();
  for (const r of rows) for (const d of r.cells.values()) used.add(bucketOf(d));
  return (
    <div className="space-y-3">
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-foreground-secondary" aria-label="Legend">
        {DAY_BUCKETS.filter((b) => used.has(b)).map((b) => (
          <li key={b} className="flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className={cn("inline-flex h-5 min-w-5 items-center justify-center rounded px-1 text-[10px] font-semibold", BUCKET_TONES[b].cell)}
            >
              {BUCKET_GLYPHS[b]}
            </span>
            {BUCKET_LABELS[b]}
          </li>
        ))}
      </ul>
      <div className="max-h-[70vh] overflow-auto rounded-xl border border-border bg-surface">
        <table className="w-full border-separate border-spacing-0 text-xs">
          <caption className="sr-only">Attendance status by employee and day</caption>
          <thead>
            <tr>
              <th scope="col" className="sticky left-0 top-0 z-30 min-w-[12rem] border-b border-border bg-surface-secondary px-3 py-2 text-left font-medium text-foreground-muted">
                Employee
              </th>
              {dates.map((d) => {
                const dow = new Date(`${d}T00:00:00Z`).getUTCDay();
                return (
                  <th
                    key={d}
                    scope="col"
                    className={cn(
                      "sticky top-0 z-20 min-w-8 border-b border-border bg-surface-secondary px-0.5 py-1.5 text-center font-medium",
                      d === today ? "text-primary" : dow === 0 || dow === 6 ? "text-foreground-disabled" : "text-foreground-muted",
                    )}
                  >
                    <div>{d.slice(8)}</div>
                    <div className="text-[10px] font-normal">{"SMTWTFS"[dow]}</div>
                  </th>
                );
              })}
              {["P", "A", "L", "Late"].map((h) => (
                <th key={h} scope="col" className="sticky top-0 z-20 min-w-9 border-b border-l border-border bg-surface-secondary px-1 py-2 text-center font-medium text-foreground-muted first:border-l">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.employeeId}>
                <th scope="row" className="sticky left-0 z-10 border-b border-border bg-surface px-3 py-1.5 text-left font-medium">
                  <button type="button" onClick={() => onPickEmployee(row)} className="text-left text-foreground hover:underline">
                    {row.name}
                  </button>
                  {row.code ? <span className="ml-1 font-normal text-foreground-muted">{row.code}</span> : null}
                </th>
                {dates.map((d) => {
                  const day = row.cells.get(d);
                  if (!day) {
                    return (
                      <td key={d} className="border-b border-border p-0.5 text-center text-foreground-disabled">
                        ·
                      </td>
                    );
                  }
                  const bucket = bucketOf(day);
                  return (
                    <td key={d} className="border-b border-border p-0.5 text-center">
                      <button
                        type="button"
                        onClick={() => onPickDay(row, day)}
                        title={tooltip(row, day)}
                        aria-label={tooltip(row, day)}
                        className={cn(
                          "flex h-7 w-full min-w-7 items-center justify-center rounded text-[10px] font-semibold hover:ring-1 hover:ring-border-strong",
                          BUCKET_TONES[bucket].cell,
                          d === today && "ring-1 ring-primary",
                        )}
                      >
                        {BUCKET_GLYPHS[bucket]}
                      </button>
                    </td>
                  );
                })}
                <td className="border-b border-l border-border px-1 text-center tabular-nums text-success">{row.present}</td>
                <td className="border-b border-border px-1 text-center tabular-nums text-danger">{row.absent}</td>
                <td className="border-b border-border px-1 text-center tabular-nums text-on-leave">{row.leave}</td>
                <td className="border-b border-border px-1 text-center tabular-nums text-warning">{row.late}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-foreground-muted">
        P = days present, A = absent, L = on leave, Late = late arrivals. “·” means no attendance record for that day.
      </p>
    </div>
  );
}
