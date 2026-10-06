import Link from "next/link";

import {
  BUCKET_GLYPHS,
  BUCKET_LABELS,
  BUCKET_TONES,
  DAY_BUCKETS,
  bucketOf,
  formatShortDate,
  monthGrid,
} from "@/lib/attendance/dashboard";
import type { AttendanceDay } from "@/lib/attendance/types";
import { cn } from "@/lib/utils";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** One employee's month. Each day shows its number, a status glyph and (to assistive tech) the
 * full status — colour is never the only signal. Days link to the existing day detail page. */
export function MonthCalendar({ month, days }: { month: string; days: AttendanceDay[] }) {
  const byDate = new Map(days.map((d) => [d.attendance_date, d]));
  const weeks = monthGrid(month, byDate);
  const used = new Set(days.map(bucketOf));
  return (
    <div className="space-y-3">
      <div role="grid" aria-label={`Attendance calendar for ${month}`} className="grid grid-cols-7 gap-1">
        {WEEKDAYS.map((w) => (
          <div key={w} role="columnheader" className="pb-1 text-center text-xs font-medium text-foreground-muted">
            {w}
          </div>
        ))}
        {weeks.flat().map((cell, i) => {
          if (!cell) return <div key={`pad-${i}`} role="gridcell" aria-hidden="true" />;
          const date = "attendance_date" in cell ? cell.attendance_date : cell.date;
          const dayNum = Number(date.slice(8));
          if (!("attendance_date" in cell)) {
            return (
              <div key={date} role="gridcell" className="flex h-12 flex-col items-center justify-center rounded-md border border-dashed border-border text-xs text-foreground-disabled">
                {dayNum}
                <span className="sr-only">{formatShortDate(date)}: no record</span>
              </div>
            );
          }
          const bucket = bucketOf(cell);
          return (
            <Link
              key={date}
              role="gridcell"
              href={`/app/attendance/${cell.id}`}
              title={`${formatShortDate(date)} — ${BUCKET_LABELS[bucket]}`}
              className={cn("flex h-12 flex-col items-center justify-center rounded-md text-xs font-medium hover:ring-1 hover:ring-border-strong", BUCKET_TONES[bucket].cell)}
            >
              <span>{dayNum}</span>
              <span aria-hidden="true" className="text-[10px] font-semibold">{BUCKET_GLYPHS[bucket]}</span>
              <span className="sr-only">{formatShortDate(date)}: {BUCKET_LABELS[bucket]}</span>
            </Link>
          );
        })}
      </div>
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-foreground-secondary" aria-label="Legend">
        {DAY_BUCKETS.filter((b) => used.has(b)).map((b) => (
          <li key={b} className="flex items-center gap-1.5">
            <span className={cn("inline-flex h-5 min-w-5 items-center justify-center rounded px-1 text-[10px] font-semibold", BUCKET_TONES[b].cell)} aria-hidden="true">
              {BUCKET_GLYPHS[b]}
            </span>
            {BUCKET_LABELS[b]}
          </li>
        ))}
      </ul>
    </div>
  );
}
