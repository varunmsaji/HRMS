"use client";

import { DeltaChip } from "@/components/attendance/dashboard/delta-chip";
import { ProportionBar, Sparkline } from "@/components/attendance/dashboard/charts";
import {
  BUCKET_TONES,
  formatPct,
  pct,
  type DashboardFilters,
  type DayBucket,
  type DistributionEntry,
} from "@/lib/attendance/dashboard";
import { weekdayShort, type RateComparison, type RatePoint } from "@/lib/attendance/insights";
import { cn } from "@/lib/utils";

interface TodayPulseProps {
  /** Daily attendance rate over the trend window, oldest first. */
  points: RatePoint[];
  focusDate: string;
  /** "today" or a short date — how the focus day is named in copy. */
  focusLabel: string;
  comparison: RateComparison;
  distribution: DistributionEntry[];
  filters: DashboardFilters;
  onDrill: (bucket: DayBucket) => void;
}

const SPARK_DAYS = 14;

/** The one-glance answer to "how are we doing?": the attendance rate, whether it's better or
 * worse than the same weekday last week, the last two weeks as a trend, and who makes up the
 * day. Every status in the breakdown is a drill-down into the employee list. */
export function TodayPulse({ points, focusDate, focusLabel, comparison, distribution, filters, onDrill }: TodayPulseProps) {
  const focus = points.find((p) => p.date === focusDate);
  const rate = focus?.rate ?? null;
  const visible = distribution.filter((d) => d.count > 0);
  const total = distribution.reduce((acc, d) => acc + d.count, 0);
  const spark = points.filter((p) => p.date <= focusDate).slice(-SPARK_DAYS);

  return (
    <section
      aria-label="Attendance at a glance"
      className="grid gap-6 rounded-xl border border-border bg-gradient-to-br from-primary-subtle/50 via-surface to-surface p-5 shadow-elevation-1 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-8"
    >
      <div className="min-w-0">
        <p className="text-2xs font-semibold uppercase tracking-wider text-foreground-muted">
          Attendance rate {focusLabel === "today" ? "today" : `· ${focusLabel}`}
        </p>
        <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
          <p className="text-4xl font-bold tabular-nums tracking-tight text-foreground">
            {rate === null ? "—" : formatPct(rate)}
          </p>
          <DeltaChip delta={comparison.delta} good="up" unit=" pts" decimals={1} versus={`last ${weekdayShort(comparison.baselineDate)}`} />
        </div>
        <p className="mt-1 text-xs text-foreground-secondary">
          {rate === null
            ? "Nobody was expected to work on this day."
            : `${focus?.present ?? 0} of ${focus?.expected ?? 0} expected employees attended.`}
        </p>
        <Sparkline
          className="mt-3"
          values={spark.map((p) => p.rate)}
          yMin={0}
          yMax={100}
          ariaLabel={`Attendance rate for the last ${spark.length} days`}
        />
        <p className="text-[11px] text-foreground-muted">Last {spark.length} days</p>
      </div>

      <div className="min-w-0 self-center">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-2xs font-semibold uppercase tracking-wider text-foreground-muted">Who&apos;s who</p>
          <p className="text-xs text-foreground-muted tabular-nums">{total} records</p>
        </div>
        <ProportionBar
          className="mt-2 h-4 shadow-inner"
          ariaLabel={`Status breakdown across ${total} attendance records`}
          segments={visible.map((d) => ({ key: d.bucket, label: d.label, count: d.count, barClass: BUCKET_TONES[d.bucket].bar }))}
        />
        {visible.length === 0 ? (
          <p className="mt-3 text-sm text-foreground-secondary">No attendance records for this date.</p>
        ) : (
          <ul className="mt-3 flex flex-wrap gap-2">
            {visible.map((entry) => {
              const active = !filters.scope && filters.bucket === entry.bucket;
              return (
                <li key={entry.bucket}>
                  <button
                    type="button"
                    onClick={() => onDrill(entry.bucket)}
                    aria-pressed={active}
                    aria-label={`Show ${entry.label} employees (${entry.count})`}
                    className={cn(
                      "inline-flex items-center gap-2 rounded-full border bg-surface px-3 py-1.5 text-sm transition-[transform,colors] duration-motion-fast active:scale-95 motion-reduce:transform-none hover:border-border-strong hover:bg-surface-secondary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      active ? "border-primary ring-1 ring-primary" : "border-border",
                    )}
                  >
                    <span className={cn("h-2.5 w-2.5 rounded-full", BUCKET_TONES[entry.bucket].bar)} aria-hidden="true" />
                    <span className="text-foreground-secondary">{entry.label}</span>
                    <span className="font-semibold tabular-nums text-foreground">{entry.count}</span>
                    <span className="text-xs tabular-nums text-foreground-muted">{formatPct(pct(entry.count, total))}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
