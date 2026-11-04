"use client";

import { ArrowDown, ArrowUp, Banknote, ChevronRight } from "lucide-react";
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
            <span className="min-w-0 flex-1 truncate text-foreground-secondary" title={s.label}>{s.label}</span>
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

/** Headcount per month-end as a trend line with the current figure and the change over the
 * period. The line is scaled to the data's own range (padded), not to zero — a flat 60→64 trend
 * would otherwise be six identical bars; every point is labelled with its real value, so the
 * scale cannot mislead. */
export function GrowthChart({ points }: { points: HeadcountPoint[] }) {
  if (points.length === 0) return <Empty>No headcount history yet.</Empty>;

  const values = points.map((p) => p.headcount);
  const first = points[0];
  const last = points[points.length - 1];
  const delta = last.headcount - first.headcount;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = Math.max((max - min) * 0.35, 1);
  const lo = min - pad;
  const hi = max + pad;
  const n = points.length;
  const xs = points.map((_, i) => (n === 1 ? 50 : (i / (n - 1)) * 100));
  const ys = values.map((v) => (1 - (v - lo) / (hi - lo)) * 100);
  const line = xs.map((x, i) => `${i === 0 ? "M" : "L"} ${x} ${ys[i]}`).join(" ");
  const area = `${line} L ${xs[n - 1]} 100 L ${xs[0]} 100 Z`;
  const summary = `Employee headcount by month, from ${first.headcount} in ${monthShort(first.month)} to ${last.headcount} in ${monthShort(last.month)}`;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-3xl font-bold tabular-nums tracking-tight text-foreground">{last.headcount}</span>
        <span className="text-sm text-foreground-secondary">employees</span>
        <span
          className={cn(
            "ml-1 inline-flex items-center gap-0.5 text-xs font-medium",
            delta > 0 ? "text-success" : delta < 0 ? "text-danger" : "text-foreground-muted",
          )}
        >
          {delta > 0 ? <ArrowUp className="h-3 w-3" aria-hidden="true" /> : null}
          {delta < 0 ? <ArrowDown className="h-3 w-3" aria-hidden="true" /> : null}
          {delta === 0 ? "No change" : `${delta > 0 ? "+" : ""}${delta}`} since {monthShort(first.month)}
        </span>
      </div>

      <div className="relative h-44" role="img" aria-label={summary}>
        <div className="absolute inset-x-5 bottom-7 top-6">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-full w-full overflow-visible" aria-hidden="true">
            {[0, 50, 100].map((y) => (
              <line key={y} x1="0" x2="100" y1={y} y2={y} vectorEffect="non-scaling-stroke" className="stroke-border-subtle" strokeDasharray="3 3" />
            ))}
            <path d={area} className="fill-primary/10" />
            <path d={line} fill="none" vectorEffect="non-scaling-stroke" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" className="stroke-primary" />
          </svg>
          {points.map((p, i) => (
            <span
              key={p.month}
              aria-hidden="true"
              className="absolute"
              style={{ left: `${xs[i]}%`, top: `${ys[i]}%` }}
            >
              <span
                className={cn(
                  "absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-primary",
                  i === n - 1 ? "h-3.5 w-3.5 ring-2 ring-primary/30" : "h-2 w-2",
                )}
              />
              <span
                className={cn(
                  "absolute -translate-x-1/2 -translate-y-full whitespace-nowrap pb-2 text-2xs tabular-nums",
                  i === n - 1 ? "font-semibold text-foreground" : "text-foreground-muted",
                )}
              >
                {p.headcount}
              </span>
            </span>
          ))}
        </div>
        <div className="absolute inset-x-5 bottom-0 h-5">
          {points.map((p, i) => (
            <span
              key={p.month}
              aria-hidden="true"
              className="absolute -translate-x-1/2 text-2xs text-foreground-muted"
              style={{ left: `${xs[i]}%` }}
            >
              {monthShort(p.month)}
            </span>
          ))}
        </div>
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
            {a.kind.startsWith("PAYROLL_") ? (
              <Banknote className="h-4 w-4" aria-hidden="true" />
            ) : (
              initials(a.subject ?? a.title)
            )}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-foreground" title={a.title}>
              {a.title}
            </p>
            <p className="truncate text-xs text-foreground-muted">
              {a.subject ? `${a.subject} · ` : ""}
              {relativeTime(a.occurred_at)}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}
