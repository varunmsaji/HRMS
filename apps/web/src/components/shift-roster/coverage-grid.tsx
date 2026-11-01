"use client";

import { Moon, Users } from "lucide-react";

import type { Coverage } from "@/lib/shift-roster/coverage";
import { cn } from "@/lib/utils";

interface Props {
  coverage: Coverage;
  dates: string[];
  today: string;
  /** Employees in the company, for "N of M rostered"; null when the directory total is unknown. */
  totalEmployees: number | null;
  /** The roster range holds more entries than were loaded, so counts may be low. */
  truncated: boolean;
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 shadow-elevation-1">
      <p className="text-sm text-foreground-secondary">{label}</p>
      <p className="mt-2 text-3xl font-bold tabular-nums tracking-tight text-foreground">{value}</p>
      {note ? <p className="mt-2 text-xs text-foreground-muted">{note}</p> : null}
    </div>
  );
}

function dayHead(iso: string) {
  const dt = new Date(`${iso}T00:00:00Z`);
  return {
    weekday: dt.toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" }),
    label: dt.toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" }),
  };
}

/** Shifts as rows, days as columns, each cell the headcount rostered on that shift that day. */
export function CoverageGrid({ coverage, dates, today, totalEmployees, truncated }: Props) {
  const shiftRows = coverage.rows.filter((r) => !r.isOff);
  return (
    <section aria-label="Roster coverage" className="space-y-5">
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Rostered staff"
          value={coverage.rosteredEmployees.toLocaleString()}
          note={totalEmployees ? `of ${totalEmployees.toLocaleString()} employees in this range` : "with an entry in this range"}
        />
        <Stat label="Active shifts" value={String(shiftRows.length)} note="with at least one person rostered" />
        <Stat
          label="Published entries"
          value={(coverage.totalEntries - coverage.draftEntries).toLocaleString()}
          note={`${coverage.totalEntries.toLocaleString()} entries in total`}
        />
        <Stat
          label="Draft entries"
          value={coverage.draftEntries.toLocaleString()}
          note={coverage.draftEntries > 0 ? "Not live until published" : "Nothing waiting to publish"}
        />
      </div>

      <div className="rounded-2xl border border-border bg-surface shadow-elevation-1">
        <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
            <Users className="h-4 w-4 text-primary" aria-hidden="true" />
            Shift coverage
          </h2>
          <span className="rounded-full bg-muted px-2.5 py-0.5 text-2xs font-medium text-foreground-secondary">
            {shiftRows.length} active {shiftRows.length === 1 ? "shift" : "shifts"}
          </span>
        </div>
        {truncated ? (
          <p role="note" className="border-b border-border bg-warning-subtle px-5 py-2 text-xs text-foreground">
            Only part of the entries for this range could be loaded, so counts may be low. Choose a shorter range.
          </p>
        ) : null}
        {coverage.rows.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-foreground-muted">No roster entries in this range.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="bg-muted/40 text-2xs uppercase tracking-wider text-foreground-muted">
                  <th className="sticky left-0 z-10 min-w-44 bg-muted px-5 py-3 text-left font-semibold">Shift</th>
                  {dates.map((d) => {
                    const h = dayHead(d);
                    return (
                      <th
                        key={d}
                        className={cn("px-3 py-3 text-center font-semibold", d === today && "text-primary")}
                      >
                        <div>{h.weekday}</div>
                        <div className="font-normal normal-case">{h.label}</div>
                        {d === today ? (
                          <span className="mt-1 inline-block rounded bg-primary px-1.5 py-0.5 text-[10px] text-on-primary">
                            Today
                          </span>
                        ) : null}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {coverage.rows.map((row) => (
                  <tr key={row.key} className="border-t border-border">
                    <th scope="row" className="sticky left-0 z-10 bg-surface px-5 py-3 text-left font-medium text-foreground">
                      <span className="flex items-center gap-2">
                        {row.isOff ? <Moon className="h-3.5 w-3.5 text-foreground-muted" aria-hidden="true" /> : null}
                        {row.label}
                      </span>
                      <span className="text-xs font-normal text-foreground-muted">
                        {row.people} {row.people === 1 ? "person" : "people"}
                      </span>
                    </th>
                    {dates.map((d) => {
                      const n = row.byDate.get(d) ?? 0;
                      return (
                        <td key={d} className={cn("px-3 py-3 text-center", d === today && "bg-primary-subtle/40")}>
                          {n > 0 ? (
                            <span
                              className={cn(
                                "inline-flex min-w-12 justify-center rounded-lg px-2 py-1.5 text-xs font-semibold tabular-nums",
                                row.isOff ? "bg-muted text-foreground-secondary" : "bg-primary-subtle text-primary",
                              )}
                            >
                              {n} staff
                            </span>
                          ) : (
                            <span className="text-foreground-muted">—</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
