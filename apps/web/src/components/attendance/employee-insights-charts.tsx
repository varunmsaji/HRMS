"use client";

import { BUCKET_TONES } from "@/lib/attendance/dashboard";
import {
  type DailyHoursBar,
  type MonthTrendPoint,
  formatDayCount,
} from "@/lib/attendance/employee-analytics";
import { formatMinutes } from "@/lib/attendance/format";
import { cn } from "@/lib/utils";

/** Hours worked on each day, with the shift length as a dashed line, so short days and long days
 * stand out. Bars are plain elements (no chart library) with the value in their label. */
export function DailyHoursChart({
  bars,
  scheduledMinutes,
}: {
  bars: DailyHoursBar[];
  scheduledMinutes: number | null;
}) {
  if (bars.length === 0) return null;
  const top = Math.max(scheduledMinutes ?? 0, ...bars.map((b) => b.minutes), 60) * 1.1;
  const linePct = scheduledMinutes ? (scheduledMinutes / top) * 100 : null;
  return (
    <figure className="mt-6" aria-label="Hours worked each day">
      <figcaption className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-foreground">Hours each day</span>
        {scheduledMinutes ? (
          <span className="text-xs text-foreground-muted">
            Dashed line: shift length ({formatMinutes(scheduledMinutes)})
          </span>
        ) : null}
      </figcaption>
      <div className="relative h-36 rounded-xl border border-border-subtle bg-surface-secondary/40 px-2 pb-5 pt-2">
        {linePct !== null ? (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-2 border-t border-dashed border-foreground-muted/60"
            style={{ bottom: `calc(1.25rem + (100% - 1.25rem - 0.5rem) * ${linePct / 100})` }}
          />
        ) : null}
        <ul className="flex h-full items-end gap-1">
          {bars.map((b) => (
            <li
              key={b.date}
              className="group relative flex h-full min-w-0 flex-1 flex-col items-center justify-end"
              title={`${b.date}: ${formatMinutes(b.minutes)}${b.isLate ? " (late)" : ""}`}
            >
              <div
                className={cn(
                  "w-full rounded-t-sm",
                  b.isLate ? "bg-warning" : BUCKET_TONES[b.bucket].bar,
                )}
                style={{ height: `${Math.max(2, (b.minutes / top) * 100)}%` }}
              />
              <span className="absolute -bottom-4 text-[10px] tabular-nums text-foreground-muted">
                {b.dayOfMonth}
              </span>
            </li>
          ))}
        </ul>
      </div>
      <p className="mt-1 text-xs text-foreground-muted">Amber bars are late arrivals.</p>
    </figure>
  );
}

function monthName(month: string): string {
  return new Date(`${month}-01T00:00:00Z`).toLocaleDateString("en-US", { month: "short", timeZone: "UTC" });
}

/** Days worked out of days expected, month by month, with late arrivals beside each. */
export function SixMonthTrend({ points }: { points: MonthTrendPoint[] }) {
  if (points.every((p) => p.expectedDays === 0)) return null;
  return (
    <section
      aria-label="Last six months"
      className="rounded-2xl border border-border bg-surface p-5 shadow-elevation-1"
    >
      <h2 className="text-base font-semibold text-foreground">Last six months</h2>
      <p className="text-xs text-foreground-muted">Days worked out of the days expected.</p>
      <ul className="mt-4 space-y-2.5">
        {points.map((p) => {
          const pct = p.expectedDays ? Math.min(100, (p.daysWorked / p.expectedDays) * 100) : 0;
          return (
            <li key={p.month} className="grid grid-cols-[2.5rem_1fr_auto] items-center gap-3 text-sm">
              <span className="text-foreground-secondary">{monthName(p.month)}</span>
              <div
                className="h-2.5 overflow-hidden rounded-full bg-muted"
                role="img"
                aria-label={`${monthName(p.month)}: ${formatDayCount(p.daysWorked)} of ${p.expectedDays} days worked`}
              >
                <div className="h-full rounded-full bg-success" style={{ width: `${pct}%` }} />
              </div>
              <span className="min-w-28 text-right text-xs tabular-nums text-foreground-secondary">
                {p.expectedDays === 0 ? "No data" : `${formatDayCount(p.daysWorked)} of ${p.expectedDays}`}
                {p.lateDays > 0 ? <span className="text-warning"> · {p.lateDays} late</span> : null}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
