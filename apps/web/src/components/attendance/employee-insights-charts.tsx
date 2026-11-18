"use client";

import type { DayBucket } from "@/lib/attendance/dashboard";
import { BUCKET_LABELS } from "@/lib/attendance/dashboard";
import type { BreakdownItem, DailyHoursBar } from "@/lib/attendance/employee-analytics";
import { formatDayCount } from "@/lib/attendance/employee-analytics";
import { formatMinutes } from "@/lib/attendance/format";
import { cn } from "@/lib/utils";

/** Shades of the brand blue for days that count as attendance, quieter tones for the rest. Only
 * absences and incomplete days keep a warm accent, because those are the days someone needs to
 * notice. */
const SHADE: Record<DayBucket, string> = {
  PRESENT: "bg-primary",
  REMOTE: "bg-primary/70",
  ON_DUTY: "bg-primary/55",
  HALF_DAY: "bg-primary/40",
  LEAVE: "bg-primary/25",
  ABSENT: "bg-danger/80",
  INCOMPLETE: "bg-warning/80",
  CONFIG_ERROR: "bg-danger/50",
  HOLIDAY: "bg-foreground-muted/30",
  WEEKLY_OFF: "bg-foreground-muted/20",
  NON_WORKING: "bg-foreground-muted/15",
  NOT_EMPLOYED: "bg-foreground-muted/10",
};

/** Shorter than the shared labels where those would be cut off in the narrow list. */
const SHORT_LABEL: Partial<Record<DayBucket, string>> = {
  NON_WORKING: "Non-working",
  REMOTE: "Remote",
};
const label = (b: DayBucket) => SHORT_LABEL[b] ?? BUCKET_LABELS[b];

const WORKED: DayBucket[] = ["PRESENT", "REMOTE", "ON_DUTY"];
const EXPECTED: DayBucket[] = [...WORKED, "HALF_DAY", "ABSENT", "LEAVE", "INCOMPLETE"];

function Ring({ pct }: { pct: number | null }) {
  const r = 42;
  const c = 2 * Math.PI * r;
  const filled = pct === null ? 0 : (pct / 100) * c;
  return (
    <div className="relative h-28 w-28 shrink-0">
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90" aria-hidden="true">
        <circle cx="50" cy="50" r={r} fill="none" strokeWidth="10" className="stroke-primary-subtle" />
        <circle
          cx="50"
          cy="50"
          r={r}
          fill="none"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${c}`}
          className="stroke-primary transition-[stroke-dasharray] duration-500"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-semibold tabular-nums text-foreground">
          {pct === null ? "—" : `${pct}%`}
        </span>
        <span className="text-[11px] text-foreground-muted">attendance</span>
      </div>
    </div>
  );
}

/** Attendance rate as a ring, with the month's days by status beside it. */
export function StatusBreakdown({ items }: { items: BreakdownItem[] }) {
  const total = items.reduce((n, i) => n + i.count, 0);
  if (total === 0) return null;
  const count = (b: DayBucket) => items.find((i) => i.bucket === b)?.count ?? 0;
  const worked = WORKED.reduce((n, b) => n + count(b), 0) + count("HALF_DAY") * 0.5;
  const expected = EXPECTED.reduce((n, b) => n + count(b), 0);
  const pct = expected ? Math.round((worked / expected) * 100) : null;

  return (
    <section
      aria-label="Days by status"
      className="rounded-xl border border-primary-border/60 bg-primary-subtle/40 p-4"
    >
      <div className="flex flex-wrap items-center gap-5">
        <Ring pct={pct} />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-foreground">Days by status</h3>
          <p className="text-xs text-foreground-muted">
            {formatDayCount(worked)} of {expected} working days attended
          </p>
          <ul className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
            {items.map((i) => (
              <li key={i.bucket} className="flex items-center justify-between gap-2">
                <span className="inline-flex min-w-0 items-center gap-2 text-foreground-secondary">
                  <span
                    className={cn("h-2.5 w-2.5 shrink-0 rounded-full", SHADE[i.bucket])}
                    aria-hidden="true"
                  />
                  <span className="truncate">{label(i.bucket)}</span>
                </span>
                <span className="font-semibold tabular-nums text-foreground">{i.count}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div
        className="mt-4 flex h-2 gap-0.5 overflow-hidden rounded-full"
        role="img"
        aria-label={items.map((i) => `${BUCKET_LABELS[i.bucket]} ${i.count}`).join(", ")}
      >
        {items.map((i) => (
          <div key={i.bucket} className={cn("h-full", SHADE[i.bucket])} style={{ flexGrow: i.count }} />
        ))}
      </div>
    </section>
  );
}

/** Hours worked each day in brand blue, with the shift length as a dashed line. Late days are a
 * lighter blue with an amber dot, so the eye goes to them without the chart turning orange. */
export function DailyHoursChart({
  bars,
  scheduledMinutes,
}: {
  bars: DailyHoursBar[];
  scheduledMinutes: number | null;
}) {
  if (bars.length === 0) return null;
  const top = Math.max(scheduledMinutes ?? 0, ...bars.map((b) => b.minutes), 60) * 1.2;

  return (
    <figure
      aria-label="Hours worked each day"
      className="rounded-xl border border-border-subtle bg-surface p-4"
    >
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-foreground">Hours each day</span>
      </figcaption>
      {/* The plot area is its own box so the bars and the shift line share one scale. */}
      <div className="mt-4">
        <div className="relative h-28">
          {scheduledMinutes ? (
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 z-10 border-t border-dashed border-primary/60"
              style={{ bottom: `${(scheduledMinutes / top) * 100}%` }}
            >
              <span className="absolute -top-4 right-0 text-[10px] font-medium text-primary">
                Shift {formatMinutes(scheduledMinutes)}
              </span>
            </div>
          ) : null}
          <ul className="flex h-full items-end gap-1.5">
            {bars.map((b) => {
              const h = Math.max(2, (b.minutes / top) * 100);
              return (
                <li
                  key={b.date}
                  className="group relative flex h-full min-w-0 flex-1 flex-col items-center justify-end"
                >
                  <span
                    className="pointer-events-none absolute z-20 mb-1 whitespace-nowrap rounded-md bg-foreground px-1.5 py-0.5 text-[10px] font-medium text-surface opacity-0 shadow-elevation-1 transition-opacity group-hover:opacity-100"
                    style={{ bottom: `${h}%` }}
                  >
                    {formatMinutes(b.minutes)}
                    {b.isLate ? " · late" : ""}
                  </span>
                  {b.isLate ? (
                    <span className="mb-1 h-1.5 w-1.5 shrink-0 rounded-full bg-warning" aria-hidden="true" />
                  ) : null}
                  <div
                    title={`${b.date}: ${formatMinutes(b.minutes)}${b.isLate ? " (late)" : ""}`}
                    className={cn(
                      "w-full max-w-7 rounded-t-md bg-gradient-to-t transition-opacity group-hover:opacity-80",
                      b.isLate ? "from-primary/25 to-primary/45" : "from-primary/60 to-primary",
                    )}
                    style={{ height: `${h}%` }}
                  />
                </li>
              );
            })}
          </ul>
        </div>
        <ul className="mt-1 flex gap-1.5 border-t border-border-subtle pt-1" aria-hidden="true">
          {bars.map((b) => (
            <li key={b.date} className="flex-1 text-center text-[10px] tabular-nums text-foreground-muted">
              {b.dayOfMonth}
            </li>
          ))}
        </ul>
      </div>
      <p className="mt-2 flex items-center gap-1.5 text-xs text-foreground-muted">
        <span className="h-1.5 w-1.5 rounded-full bg-warning" aria-hidden="true" />
        Late arrival
      </p>
    </figure>
  );
}
