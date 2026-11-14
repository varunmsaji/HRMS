"use client";

import { useMemo, useState } from "react";

import { LineChart } from "@/components/attendance/dashboard/charts";
import { NativeSelect } from "@/components/ui/native-select";
import {
  TREND_METRICS,
  TREND_METRIC_LABELS,
  buildTrend,
  dayDiff,
  formatPct,
  type DateRange,
  type TrendGranularity,
  type TrendMetric,
} from "@/lib/attendance/dashboard";
import type { SummaryDay } from "@/lib/attendance/summary";

interface TrendChartProps {
  /** The summary's per-day counts for `range`. */
  days: SummaryDay[];
  range: DateRange;
}

export function formatTrendValue(metric: TrendMetric, value: number): string {
  return metric === "avg_hours" ? `${value.toFixed(1)}h` : formatPct(value);
}

/** One metric at a time (selector) rather than a tangle of lines. Percentages use expected
 * working days as the denominator, so weekends and holidays don't read as absence. */
export function TrendChart({ days, range }: TrendChartProps) {
  const [metric, setMetric] = useState<TrendMetric>("present_pct");
  const [granularity, setGranularity] = useState<TrendGranularity>("daily");
  const canWeek = dayDiff(range.from, range.to) >= 13;
  const effective: TrendGranularity = canWeek ? granularity : "daily";
  const points = useMemo(() => buildTrend(days, range, metric, effective), [days, range, metric, effective]);
  const hasData = points.some((p) => p.value !== null);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="att-trend-metric" className="sr-only">
          Trend metric
        </label>
        <NativeSelect id="att-trend-metric" className="w-44" value={metric} onChange={(e) => setMetric(e.target.value as TrendMetric)}>
          {TREND_METRICS.map((m) => (
            <option key={m} value={m}>
              {TREND_METRIC_LABELS[m]}
            </option>
          ))}
        </NativeSelect>
        {canWeek ? (
          <div role="group" aria-label="Granularity" className="inline-flex rounded-md border border-border p-0.5 text-sm">
            {(["daily", "weekly"] as const).map((g) => (
              <button
                key={g}
                type="button"
                aria-pressed={effective === g}
                onClick={() => setGranularity(g)}
                className={`rounded px-2.5 py-1 capitalize ${effective === g ? "bg-primary text-on-primary" : "text-foreground-secondary hover:bg-muted"}`}
              >
                {g}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      {hasData ? (
        <LineChart
          points={points}
          ariaLabel={`${TREND_METRIC_LABELS[metric]}, ${effective}`}
          format={(v) => formatTrendValue(metric, v)}
          yMax={metric === "avg_hours" ? undefined : 100}
        />
      ) : (
        <p className="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-foreground-secondary">
          No attendance recorded in this range to chart.
        </p>
      )}
    </div>
  );
}
