import { ProportionBar } from "@/components/attendance/dashboard/charts";
import {
  BUCKET_TONES,
  formatPct,
  pct,
  type DashboardFilters,
  type DayBucket,
  type DistributionEntry,
} from "@/lib/attendance/dashboard";
import { cn } from "@/lib/utils";

interface StatusChartProps {
  distribution: DistributionEntry[];
  filters: DashboardFilters;
  onDrill: (bucket: DayBucket) => void;
}

/** Status distribution for the focus date over the backend's own status model. Each row is a
 * drill-down into the Who's In list. */
export function StatusChart({ distribution, filters, onDrill }: StatusChartProps) {
  const total = distribution.reduce((acc, d) => acc + d.count, 0);
  const visible = distribution.filter((d) => d.count > 0);
  return (
    <div className="space-y-4">
      <ProportionBar
        ariaLabel={`Status distribution across ${total} attendance records`}
        segments={visible.map((d) => ({ key: d.bucket, label: d.label, count: d.count, barClass: BUCKET_TONES[d.bucket].bar }))}
      />
      <ul className="space-y-1">
        {visible.map((entry) => {
          // Same reasoning as kpi-grid.tsx: a range-scoped Needs Attention drill sharing this
          // bucket filters a different (whole-range) population, so it is never "active" here.
          const active = !filters.scope && filters.bucket === entry.bucket;
          return (
            <li key={entry.bucket}>
              <button
                type="button"
                onClick={() => onDrill(entry.bucket)}
                aria-pressed={active}
                aria-label={`${entry.label}: ${entry.count}. Show these employees.`}
                className={cn(
                  "flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active && "bg-muted",
                )}
              >
                <span className={cn("h-2.5 w-2.5 shrink-0 rounded-sm", BUCKET_TONES[entry.bucket].bar)} aria-hidden="true" />
                <span className="flex-1 text-foreground">{entry.label}</span>
                <span className="tabular-nums font-medium text-foreground">{entry.count}</span>
                <span className="w-14 text-right text-xs tabular-nums text-foreground-muted">
                  {formatPct(pct(entry.count, total))}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
