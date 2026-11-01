"use client";

import { Building2, CalendarClock, LogOut, Users, type LucideIcon } from "lucide-react";

import type { DirectorySummary } from "@/lib/employee/directory";
import { cn } from "@/lib/utils";

function Stat({
  label,
  value,
  icon: Icon,
  tile,
  children,
}: {
  label: string;
  value: number | null;
  icon: LucideIcon;
  tile: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 shadow-elevation-1">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-2xs font-semibold uppercase tracking-wider text-foreground-muted">{label}</p>
          <p className="mt-2 text-3xl font-bold tabular-nums tracking-tight text-foreground">
            {value === null ? "—" : value.toLocaleString()}
          </p>
        </div>
        <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", tile)}>
          <Icon className="h-5 w-5" aria-hidden="true" />
        </span>
      </div>
      {children ? <div className="mt-3 truncate text-xs text-foreground-muted">{children}</div> : null}
    </div>
  );
}

/** The four headline counts above the directory. `summary` null = not loaded (dash, no zeros). */
export function DirectorySummaryCards({ summary }: { summary: DirectorySummary | null }) {
  return (
    <section aria-label="Directory summary" className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
      <Stat label="Total employees" value={summary?.total ?? null} icon={Users} tile="bg-primary-subtle text-primary">
        {summary ? `${summary.active} active` : null}
      </Stat>
      <Stat label="On probation" value={summary?.on_probation ?? null} icon={CalendarClock} tile="bg-warning-subtle text-warning" />
      <Stat label="On notice" value={summary?.on_notice ?? null} icon={LogOut} tile="bg-info-subtle text-info" />
      <Stat label="Departments" value={summary?.department_count ?? null} icon={Building2} tile="bg-muted text-foreground-secondary">
        {summary && summary.department_names.length > 0 ? summary.department_names.join(", ") : null}
      </Stat>
    </section>
  );
}
