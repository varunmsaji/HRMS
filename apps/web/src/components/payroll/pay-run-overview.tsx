"use client";

import { Banknote, Building, CheckCircle2, Circle, Users, Wallet, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { preDisbursalChecklist } from "@/lib/payroll/checklist";
import { formatInr, type PayRun } from "@/lib/payroll/types";
import { cn } from "@/lib/utils";

function Card({
  label,
  value,
  note,
  icon: Icon,
  tile,
  emphasis = false,
}: {
  label: string;
  value: ReactNode;
  note: ReactNode;
  icon: LucideIcon;
  tile: string;
  emphasis?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 shadow-elevation-1">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-foreground-secondary">{label}</p>
        <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", tile)}>
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
      </div>
      <p
        className={cn(
          "mt-3 text-2xl font-bold tabular-nums tracking-tight",
          emphasis ? "text-primary" : "text-foreground",
        )}
      >
        {value}
      </p>
      <p className="mt-2 text-xs text-foreground-muted">{note}</p>
    </div>
  );
}

/** The four headline totals for a pay run. Figures are shown only once the run has been computed. */
export function PayRunStatCards({ run, computed }: { run: PayRun; computed: boolean }) {
  const dash = "—";
  return (
    <section aria-label="Pay run totals" className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
      <Card
        label="Total gross payroll"
        value={computed ? formatInr(run.gross_minor) : dash}
        note="Before deductions"
        icon={Wallet}
        tile="bg-primary-subtle text-primary"
      />
      <Card
        label="Deductions"
        value={computed ? formatInr(run.deductions_minor) : dash}
        note="Statutory and other, employee share"
        icon={Building}
        tile="bg-warning-subtle text-warning"
      />
      <Card
        label="Net payable"
        value={computed ? formatInr(run.net_minor) : dash}
        note={`${run.employee_count} ${run.employee_count === 1 ? "employee" : "employees"}`}
        icon={Users}
        tile="bg-success-subtle text-success"
        emphasis={computed}
      />
      <Card
        label="Employer contributions"
        value={computed ? formatInr(run.employer_contributions_minor) : dash}
        note="Paid by the company on top of gross"
        icon={Banknote}
        tile="bg-info-subtle text-info"
      />
    </section>
  );
}

/** The pre-disbursal checks, read from the run's own recorded state. */
export function PreDisbursalChecklist({ run }: { run: PayRun }) {
  const items = preDisbursalChecklist(run);
  const done = items.filter((i) => i.done).length;
  return (
    <section
      aria-label="Pre-disbursal checklist"
      className="rounded-2xl border border-border bg-surface p-5 shadow-elevation-1"
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
          <CheckCircle2 className={cn("h-5 w-5", done === items.length ? "text-success" : "text-foreground-muted")} aria-hidden="true" />
          Pre-disbursal checklist ({done}/{items.length} completed)
        </h2>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {items.map((item, i) => (
          <li
            key={item.key}
            className={cn(
              "flex items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm",
              item.done
                ? "border-success/30 bg-success-subtle text-success"
                : "border-border bg-muted/40 text-foreground-secondary",
            )}
          >
            <span>
              {i + 1}. {item.label}
            </span>
            {item.done ? (
              <CheckCircle2 className="h-4 w-4 shrink-0" aria-label="Done" />
            ) : (
              <Circle className="h-4 w-4 shrink-0" aria-label="Pending" />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
