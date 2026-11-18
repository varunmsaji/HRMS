"use client";

import { DeltaChip } from "@/components/attendance/dashboard/delta-chip";
import { Sparkline } from "@/components/attendance/dashboard/charts";
import { formatPct } from "@/lib/attendance/dashboard";
import { weekdayShort, type RateComparison, type RatePoint } from "@/lib/attendance/insights";

interface TodayPulseProps {
  /** Daily attendance rate over the trend window, oldest first. */
  points: RatePoint[];
  focusDate: string;
  /** "today" or a short date — how the focus day is named in copy. */
  focusLabel: string;
  comparison: RateComparison;
  /** True when no employee has an attendance row for the focus day yet (nothing calculated).
   * "Nobody was expected" would be wrong then, and a comparison with a full week-ago day is noise. */
  awaitingRecords?: boolean;
}

const SPARK_DAYS = 14;

/** The attendance rate for the focus day: the figure, whether it's better or worse than the same
 * weekday last week, and the last two weeks as a trend. The status counts sit beside it in
 * `KpiGrid`; they are not repeated here. */
export function TodayPulse({ points, focusDate, focusLabel, comparison, awaitingRecords = false }: TodayPulseProps) {
  const focus = points.find((p) => p.date === focusDate);
  const rate = focus?.rate ?? null;
  const spark = points.filter((p) => p.date <= focusDate).slice(-SPARK_DAYS);

  return (
    <section
      aria-label="Attendance at a glance"
      className="min-w-0 rounded-xl border border-border bg-gradient-to-br from-primary-subtle/50 via-surface to-surface p-5 shadow-elevation-1"
    >
      <p className="text-2xs font-semibold uppercase tracking-wider text-foreground-muted">
        Attendance rate {focusLabel === "today" ? "today" : `· ${focusLabel}`}
      </p>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
        <p className="text-4xl font-bold tabular-nums tracking-tight text-foreground">
          {rate === null ? "—" : formatPct(rate)}
        </p>
        {awaitingRecords ? null : (
          <DeltaChip delta={comparison.delta} good="up" unit=" pts" decimals={1} versus={`last ${weekdayShort(comparison.baselineDate)}`} />
        )}
      </div>
      <p className="mt-1 text-xs text-foreground-secondary">
        {rate === null
          ? awaitingRecords
            ? focusLabel === "today"
              ? "Attendance for today hasn't been calculated yet."
              : `No attendance records for ${focusLabel}.`
            : "Nobody was expected to work on this day."
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
    </section>
  );
}
