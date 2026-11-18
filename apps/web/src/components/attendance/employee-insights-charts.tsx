"use client";

import { BUCKET_LABELS, BUCKET_TONES } from "@/lib/attendance/dashboard";
import type { BreakdownItem, DailyHoursBar } from "@/lib/attendance/employee-analytics";
import { formatMinutes } from "@/lib/attendance/format";
import { cn } from "@/lib/utils";

/** The month's days split by status: one stacked bar and a count per status. */
export function StatusBreakdown({ items }: { items: BreakdownItem[] }) {
  const total = items.reduce((n, i) => n + i.count, 0);
  if (total === 0) return null;
  return (
    <section aria-label="Days by status">
      <h3 className="text-sm font-semibold text-foreground">Days by status</h3>
      <div className="mt-2 flex h-3 overflow-hidden rounded-full bg-muted" role="img" aria-label={items.map((i) => `${BUCKET_LABELS[i.bucket]} ${i.count}`).join(", ")}>
        {items.map((i) => (
          <div
            key={i.bucket}
            className={BUCKET_TONES[i.bucket].bar}
            style={{ width: `${(i.count / total) * 100}%` }}
            title={`${BUCKET_LABELS[i.bucket]}: ${i.count}`}
          />
        ))}
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
        {items.map((i) => (
          <li key={i.bucket} className="flex items-center justify-between gap-2">
            <span className="inline-flex items-center gap-2 text-foreground-secondary">
              <span className={cn("h-2.5 w-2.5 rounded-sm", BUCKET_TONES[i.bucket].bar)} aria-hidden="true" />
              {BUCKET_LABELS[i.bucket]}
            </span>
            <span className="font-semibold tabular-nums text-foreground">{i.count}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Hours worked each day with the shift length as a dashed line, so short and long days stand out. */
export function DailyHoursChart({ bars, scheduledMinutes }: { bars: DailyHoursBar[]; scheduledMinutes: number | null }) {
  if (bars.length === 0) return null;
  const top = Math.max(scheduledMinutes ?? 0, ...bars.map((b) => b.minutes), 60) * 1.1;
  const linePct = scheduledMinutes ? (scheduledMinutes / top) * 100 : null;
  return (
    <figure aria-label="Hours worked each day">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-foreground">Hours each day</span>
        {scheduledMinutes ? (
          <span className="text-xs text-foreground-muted">Dashed line: shift ({formatMinutes(scheduledMinutes)})</span>
        ) : null}
      </figcaption>
      <div className="relative mt-2 h-28 rounded-lg border border-border-subtle bg-surface-secondary/40 px-2 pb-5 pt-2">
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
              className="relative flex h-full min-w-0 flex-1 flex-col items-center justify-end"
              title={`${b.date}: ${formatMinutes(b.minutes)}${b.isLate ? " (late)" : ""}`}
            >
              <div
                className={cn("w-full rounded-t-sm", b.isLate ? "bg-warning" : BUCKET_TONES[b.bucket].bar)}
                style={{ height: `${Math.max(2, (b.minutes / top) * 100)}%` }}
              />
              <span className="absolute -bottom-4 text-[10px] tabular-nums text-foreground-muted">{b.dayOfMonth}</span>
            </li>
          ))}
        </ul>
      </div>
      <p className="mt-1 text-xs text-foreground-muted">Amber bars are late arrivals.</p>
    </figure>
  );
}
