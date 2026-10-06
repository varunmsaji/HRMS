import Link from "next/link";

import {
  BUCKET_GLYPHS,
  BUCKET_LABELS,
  BUCKET_TONES,
  DAY_BUCKETS,
  bucketOf,
  formatShortDate,
  type Muster,
} from "@/lib/attendance/dashboard";
import { cn } from "@/lib/utils";

const ROW_LIMIT = 100;

/** Organisation heatmap / muster: one row per employee, one column per day, each cell the day's
 * status. Every cell carries a letter code and a text label as well as colour. */
export function MusterHeatmap({ muster }: { muster: Muster }) {
  const rows = muster.rows.slice(0, ROW_LIMIT);
  return (
    <div className="space-y-3">
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-foreground-secondary" aria-label="Legend">
        {DAY_BUCKETS.filter((b) => b !== "NOT_EMPLOYED" && b !== "CONFIG_ERROR").map((bucket) => (
          <li key={bucket} className="flex items-center gap-1.5">
            <span className={cn("inline-flex h-5 min-w-5 items-center justify-center rounded px-1 text-[10px] font-semibold", BUCKET_TONES[bucket].cell)} aria-hidden="true">
              {BUCKET_GLYPHS[bucket]}
            </span>
            {BUCKET_LABELS[bucket]}
          </li>
        ))}
      </ul>
      <div className="max-h-[28rem] overflow-auto rounded-md border border-border">
        <table className="border-separate border-spacing-0 text-xs">
          <caption className="sr-only">Attendance status by employee and day</caption>
          <thead>
            <tr>
              <th scope="col" className="sticky left-0 top-0 z-20 min-w-[10rem] border-b border-border bg-surface-secondary px-3 py-2 text-left font-medium text-foreground-muted">
                Employee
              </th>
              {muster.dates.map((date) => (
                <th key={date} scope="col" className="sticky top-0 z-10 border-b border-border bg-surface-secondary px-1 py-2 text-center font-medium text-foreground-muted">
                  {formatShortDate(date).slice(0, 2)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.employeeId}>
                <th scope="row" className="sticky left-0 z-10 border-b border-border bg-surface px-3 py-1.5 text-left font-medium">
                  <Link href={`/app/attendance/employee/${row.employeeId}`} className="text-foreground hover:underline">
                    {row.name}
                  </Link>
                  {row.code ? <span className="ml-1.5 text-foreground-muted">{row.code}</span> : null}
                </th>
                {muster.dates.map((date) => {
                  const day = row.cells.get(date);
                  if (!day) {
                    return (
                      <td key={date} className="border-b border-border px-0.5 py-1 text-center text-foreground-disabled">
                        <span className="sr-only">{formatShortDate(date)}: no record</span>
                        <span aria-hidden="true">·</span>
                      </td>
                    );
                  }
                  const bucket = bucketOf(day);
                  return (
                    <td key={date} className="border-b border-border px-0.5 py-1 text-center">
                      <Link
                        href={`/app/attendance/${day.id}`}
                        title={`${formatShortDate(date)} — ${BUCKET_LABELS[bucket]}`}
                        className={cn("inline-flex h-6 min-w-6 items-center justify-center rounded px-1 font-semibold", BUCKET_TONES[bucket].cell)}
                      >
                        <span aria-hidden="true">{BUCKET_GLYPHS[bucket]}</span>
                        <span className="sr-only">
                          {formatShortDate(date)}: {BUCKET_LABELS[bucket]}
                        </span>
                      </Link>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {muster.rows.length > ROW_LIMIT ? (
        <p className="text-xs text-foreground-muted">
          Showing the first {ROW_LIMIT} of {muster.rows.length} employees — narrow the filters to see the rest.
        </p>
      ) : null}
    </div>
  );
}
