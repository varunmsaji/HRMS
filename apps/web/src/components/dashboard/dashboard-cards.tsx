"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import {
  birthdayLabel,
  initials,
  monthShort,
  relativeTime,
  type HeadcountPoint,
  type RecentActivity,
  type UpcomingBirthday,
} from "@/lib/dashboard/insights";
import { cn } from "@/lib/utils";

export const CARD = "rounded-2xl border border-border bg-surface p-5 shadow-elevation-1";

export function Panel({
  title,
  icon,
  action,
  children,
  className,
}: {
  title: string;
  icon?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn(CARD, "flex min-w-0 flex-col", className)} aria-label={title}>
      <div className="mb-5 flex items-start justify-between gap-3">
        <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
          {icon ? <span className="text-primary">{icon}</span> : null}
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export function ViewAll({ href }: { href: string }) {
  return (
    <Link
      href={href}
      className="inline-flex shrink-0 items-center text-xs font-medium text-primary hover:underline"
    >
      View All <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
    </Link>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-foreground-muted">{children}</p>;
}

export function Avatar({ name, src, className }: { name: string; src?: string | null; className?: string }) {
  return src ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt="" className={cn("h-10 w-10 shrink-0 rounded-full object-cover", className)} />
  ) : (
    <span
      aria-hidden="true"
      className={cn(
        "flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary-subtle text-xs font-semibold text-primary",
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}

export interface DonutSegment {
  key: string;
  label: string;
  value: number;
  stroke: string;
  dot: string;
}

/** Donut + legend. Class names are passed in as literals so Tailwind keeps them. */
export function DonutChart({
  segments,
  total,
  ariaLabel,
  centerLabel = "Total",
}: {
  segments: DonutSegment[];
  total: number;
  ariaLabel: string;
  centerLabel?: string;
}) {
  const r = 52;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="flex flex-col items-center gap-5 sm:flex-row">
      <div className="relative h-36 w-36 shrink-0">
        <svg viewBox="0 0 140 140" className="h-full w-full -rotate-90" role="img" aria-label={ariaLabel}>
          <circle cx="70" cy="70" r={r} fill="none" strokeWidth="18" className="stroke-muted" />
          {total > 0
            ? segments
                .filter((s) => s.value > 0)
                .map((s) => {
                  const len = (s.value / total) * c;
                  const el = (
                    <circle
                      key={s.key}
                      cx="70"
                      cy="70"
                      r={r}
                      fill="none"
                      strokeWidth="18"
                      strokeDasharray={`${len} ${c - len}`}
                      strokeDashoffset={-offset}
                      className={s.stroke}
                    />
                  );
                  offset += len;
                  return el;
                })
            : null}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-bold tabular-nums text-foreground">{total}</span>
          <span className="text-xs text-foreground-muted">{centerLabel}</span>
        </div>
      </div>
      <ul className="w-full min-w-0 flex-1 space-y-2">
        {segments.map((s) => (
          <li key={s.key} className="flex items-center gap-2 text-sm">
            <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", s.dot)} aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate text-foreground-secondary">{s.label}</span>
            <span className="font-semibold tabular-nums text-foreground">{s.value}</span>
            <span className="w-12 text-right text-xs tabular-nums text-foreground-muted">
              {total > 0 ? `${((s.value / total) * 100).toFixed(1)}%` : "0%"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Headcount per month-end as bars; the axis starts at zero so bar heights stay honest. */
export function GrowthChart({ points }: { points: HeadcountPoint[] }) {
  const max = Math.max(...points.map((p) => p.headcount), 1);
  const ticks = [1, 0.75, 0.5, 0.25, 0].map((f) => Math.round(max * f));
  return (
    <div className="flex h-56 gap-3" role="img" aria-label="Employee headcount by month">
      <div className="flex flex-col justify-between pb-6 text-right text-2xs tabular-nums text-foreground-muted">
        {ticks.map((t, i) => (
          <span key={i}>{t}</span>
        ))}
      </div>
      <div className="relative flex min-w-0 flex-1 items-end justify-between gap-2 border-b border-border pb-6">
        {points.map((p, i) => (
          <div key={p.month} className="relative flex h-full min-w-0 flex-1 flex-col justify-end">
            <span className="mb-1 text-center text-2xs font-medium tabular-nums text-foreground-secondary">
              {p.headcount}
            </span>
            <div
              className={cn(
                "w-full rounded-t-md",
                i === points.length - 1 ? "bg-primary" : "bg-primary/40",
              )}
              style={{ height: `${(p.headcount / max) * 85}%` }}
            />
            <span className="absolute -bottom-6 left-0 right-0 text-center text-2xs text-foreground-muted">
              {monthShort(p.month)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function BirthdayList({ items }: { items: UpcomingBirthday[] }) {
  if (items.length === 0) return <Empty>No upcoming birthdays.</Empty>;
  return (
    <ul className="space-y-4">
      {items.slice(0, 4).map((b) => (
        <li key={b.employee_id} className="flex items-center gap-3">
          <Avatar name={b.name} src={b.photo_url} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-foreground">{b.name}</p>
            {b.designation ? <p className="truncate text-xs text-foreground-muted">{b.designation}</p> : null}
          </div>
          <span
            className={cn(
              "shrink-0 rounded-md px-2 py-1 text-xs font-medium",
              b.days_until <= 1 ? "bg-primary-subtle text-primary" : "text-foreground-secondary",
            )}
          >
            {birthdayLabel(b)}
          </span>
        </li>
      ))}
    </ul>
  );
}

const ACTIVITY_TONE: Record<string, string> = {
  EMPLOYEE_CREATED: "bg-primary-subtle text-primary",
  EMPLOYEE_CONFIRMED: "bg-success-subtle text-success",
  LEAVE_APPLICATION_APPROVED: "bg-success-subtle text-success",
  REGULARIZATION_APPROVED: "bg-info-subtle text-info",
  PAYROLL_PAY_RUN_FINALISED: "bg-warning-subtle text-warning",
  PAYROLL_PAY_RUN_PAID: "bg-warning-subtle text-warning",
};

export function ActivityList({ items }: { items: RecentActivity[] }) {
  if (items.length === 0) return <Empty>No recent activity.</Empty>;
  return (
    <ul className="space-y-4">
      {items.slice(0, 4).map((a, i) => (
        <li key={`${a.kind}-${a.occurred_at}-${i}`} className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
              ACTIVITY_TONE[a.kind] ?? "bg-muted text-foreground-secondary",
            )}
          >
            {initials(a.subject ?? a.title)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-foreground">{a.title}</p>
            {a.subject ? <p className="truncate text-xs text-foreground-muted">{a.subject}</p> : null}
          </div>
          <span className="shrink-0 text-2xs text-foreground-muted">{relativeTime(a.occurred_at)}</span>
        </li>
      ))}
    </ul>
  );
}
