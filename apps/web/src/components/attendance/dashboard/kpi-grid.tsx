"use client";

import type { LucideIcon } from "lucide-react";
import {
  AlarmClock,
  AlertTriangle,
  CalendarOff,
  ChevronDown,
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock,
  Home,
  Palmtree,
  Users,
} from "lucide-react";
import { useState } from "react";

import {
  formatPct,
  pct,
  presentTotal,
  type DashboardFilters,
  type DayBucket,
  type DayFlag,
  type KpiSet,
} from "@/lib/attendance/dashboard";
import { DeltaChip, type DeltaGood } from "@/components/attendance/dashboard/delta-chip";
import { Collapse } from "@/components/common/collapse";
import { formatMinutes } from "@/lib/attendance/format";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "success" | "danger" | "warning" | "info" | "leave";

const TONE: Record<Tone, { icon: string; dot: string; value: string }> = {
  neutral: {
    icon: "bg-muted text-foreground-secondary",
    dot: "bg-foreground-muted",
    value: "text-foreground",
  },
  success: {
    icon: "bg-success-subtle text-success",
    dot: "bg-success",
    value: "text-foreground",
  },
  danger: {
    icon: "bg-danger-subtle text-danger",
    dot: "bg-danger",
    value: "text-foreground",
  },
  warning: {
    icon: "bg-warning-subtle text-warning",
    dot: "bg-warning",
    value: "text-foreground",
  },
  info: {
    icon: "bg-info-subtle text-info",
    dot: "bg-info",
    value: "text-foreground",
  },
  leave: {
    icon: "bg-on-leave-subtle text-on-leave",
    dot: "bg-on-leave",
    value: "text-foreground",
  },
};

interface Kpi {
  key: string;
  label: string;
  value: string;
  context: string;
  icon: LucideIcon;
  tone: Tone;
  /** Drill target — omitted when the card has no meaningful list behind it. */
  drill?: { bucket?: DayBucket; flag?: DayFlag; clear?: boolean };
  /** Marks the KPI as the active drill. */
  active: boolean;
  /** The raw count behind the card (0 = quiet card). */
  count: number;
  /** Change against the comparison day, when the card has one worth showing. */
  delta?: { value: number | null; good: DeltaGood; versus: string };
}

/** The day the headline cards are compared with (normally the same weekday a week earlier). */
export interface KpiComparison {
  kpi: KpiSet;
  /** Short name for the comparison day, e.g. "last Mon". */
  label: string;
}

export function buildKpis(
  kpi: KpiSet,
  filters: DashboardFilters,
  focusLabel: string,
  compare?: KpiComparison | null,
): { primary: Kpi[]; secondary: Kpi[] } {
  const present = presentTotal(kpi);
  const total = kpi.totalEmployees;
  const isActive = (target: { bucket?: DayBucket; flag?: DayFlag }) =>
    !filters.scope &&
    (target.bucket ?? "") === filters.bucket &&
    (target.flag ?? "") === filters.flag;
  const mk = (k: Omit<Kpi, "active">): Kpi => ({
    ...k,
    active: k.drill ? isActive(k.drill) : false,
  });
  const change = (now: number, before: number | undefined, good: DeltaGood): Kpi["delta"] =>
    compare ? { value: before === undefined ? null : now - before, good, versus: compare.label } : undefined;
  const ofWorkforce = (n: number) =>
    total > 0 ? `${formatPct(pct(n, total))} of workforce` : "No employees in scope";

  const primary: Kpi[] = [
    mk({
      key: "total",
      label: "Total employees",
      value: String(total),
      context:
        kpi.noRecord > 0
          ? `${kpi.noRecord} with no record yet for ${focusLabel}`
          : `Employed on ${focusLabel}`,
      icon: Users,
      tone: "neutral",
      drill: { clear: true },
      count: total,
    }),
    mk({
      key: "present",
      label: "Present",
      value: String(present),
      context: ofWorkforce(present),
      icon: CircleCheck,
      tone: "success",
      drill: { bucket: "PRESENT" },
      count: present,
      delta: change(present, compare ? presentTotal(compare.kpi) : undefined, "up"),
    }),
    mk({
      key: "absent",
      label: "Absent",
      value: String(kpi.absent),
      context: ofWorkforce(kpi.absent),
      icon: CircleX,
      tone: "danger",
      drill: { bucket: "ABSENT" },
      count: kpi.absent,
      delta: change(kpi.absent, compare?.kpi.absent, "down"),
    }),
    mk({
      key: "leave",
      label: "On leave",
      value: String(kpi.leave),
      context: ofWorkforce(kpi.leave),
      icon: Palmtree,
      tone: "leave",
      drill: { bucket: "LEAVE" },
      count: kpi.leave,
      delta: change(kpi.leave, compare?.kpi.leave, "neutral"),
    }),
    mk({
      key: "late",
      label: "Late",
      value: String(kpi.late),
      context:
        kpi.checkedIn > 0
          ? `${formatPct(pct(kpi.late, kpi.checkedIn))} of checked-in employees`
          : "Nobody checked in yet",
      icon: Clock,
      tone: "warning",
      drill: { flag: "late" },
      count: kpi.late,
      delta: change(kpi.late, compare?.kpi.late, "down"),
    }),
    mk({
      key: "not_checked_in",
      label: "Not checked in",
      value: String(kpi.notCheckedIn),
      context: "Expected to work, no IN punch",
      icon: CircleDashed,
      tone: "warning",
      drill: { flag: "not_checked_in" },
      count: kpi.notCheckedIn,
    }),
    mk({
      key: "remote",
      label: "Remote (WFH)",
      value: String(kpi.remote),
      context:
        present > 0 ? `${formatPct(pct(kpi.remote, present))} of those present` : "Nobody present",
      icon: Home,
      tone: "info",
      drill: { bucket: "REMOTE" },
      count: kpi.remote,
    }),
    mk({
      key: "overtime",
      label: "Overtime",
      value: kpi.overtimeMinutesDetected > 0 ? formatMinutes(kpi.overtimeMinutesDetected) : "None",
      context:
        kpi.overtimeEmployees > 0
          ? `${kpi.overtimeEmployees} employee${kpi.overtimeEmployees === 1 ? "" : "s"} · ${formatMinutes(kpi.overtimeMinutesApproved)} approved`
          : "No overtime detected",
      icon: AlarmClock,
      tone: "info",
      drill: { flag: "overtime" },
      count: kpi.overtimeEmployees,
    }),
  ];

  const secondary: Kpi[] = [
    mk({
      key: "on_duty",
      label: "On duty",
      value: String(kpi.onDuty),
      context: ofWorkforce(kpi.onDuty),
      icon: CircleCheck,
      tone: "info",
      drill: { bucket: "ON_DUTY" },
      count: kpi.onDuty,
    }),
    mk({
      key: "half_day",
      label: "Half day",
      value: String(kpi.halfDay),
      context: ofWorkforce(kpi.halfDay),
      icon: Clock,
      tone: "warning",
      drill: { bucket: "HALF_DAY" },
      count: kpi.halfDay,
    }),
    mk({
      key: "holiday",
      label: "Holiday",
      value: String(kpi.holiday),
      context: ofWorkforce(kpi.holiday),
      icon: CalendarOff,
      tone: "neutral",
      drill: { bucket: "HOLIDAY" },
      count: kpi.holiday,
    }),
    mk({
      key: "weekly_off",
      label: "Weekly off",
      value: String(kpi.weeklyOff),
      context: ofWorkforce(kpi.weeklyOff),
      icon: CalendarOff,
      tone: "neutral",
      drill: { bucket: "WEEKLY_OFF" },
      count: kpi.weeklyOff,
    }),
    mk({
      key: "incomplete",
      label: "Incomplete",
      value: String(kpi.incomplete),
      context: "Needs manual resolution",
      icon: AlertTriangle,
      tone: "warning",
      drill: { bucket: "INCOMPLETE" },
      count: kpi.incomplete,
    }),
    mk({
      key: "exceptions",
      label: "Exceptions",
      value: String(kpi.exceptions),
      context: "See Needs attention for the breakdown",
      icon: AlertTriangle,
      tone: "danger",
      count: kpi.exceptions,
    }),
  ];
  return { primary, secondary };
}

interface KpiGridProps {
  kpi: KpiSet;
  filters: DashboardFilters;
  focusLabel: string;
  compare?: KpiComparison | null;
  onDrill: (target: { bucket?: DayBucket; flag?: DayFlag; clear?: boolean }) => void;
}

function deltaSpeech(item: Kpi): string {
  if (!item.delta || item.delta.value === null) return "";
  const { value, versus } = item.delta;
  return value === 0 ? ` No change versus ${versus}.` : ` ${value > 0 ? "Up" : "Down"} ${Math.abs(value)} versus ${versus}.`;
}

function KpiCard({
  item,
  onDrill,
  compact,
}: {
  item: Kpi;
  onDrill: KpiGridProps["onDrill"];
  compact?: boolean;
}) {
  const tone = TONE[item.tone];
  const Icon = item.icon;
  const body = compact ? (
    <div className="flex items-center justify-between gap-2">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", tone.dot)} aria-hidden="true" />
          <p className="truncate text-xs font-medium text-foreground-secondary">{item.label}</p>
        </div>
        <p className="mt-0.5 truncate text-[11px] text-foreground-muted">{item.context}</p>
      </div>
      <p className={cn("shrink-0 text-md font-semibold tabular-nums", tone.value)}>{item.value}</p>
    </div>
  ) : (
    <>
      <div className="flex items-start justify-between gap-2">
        <p className="text-2xs font-semibold uppercase tracking-wider text-foreground-muted">
          {item.label}
        </p>
        <span
          className={cn(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-sm",
            tone.icon,
          )}
        >
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
      </div>
      <p className={cn("mt-1.5 text-xl font-semibold tabular-nums", tone.value)}>{item.value}</p>
      <p className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-foreground-secondary">
        {item.context}
      </p>
      {item.delta ? (
        <div className="mt-2">
          <DeltaChip delta={item.delta.value} good={item.delta.good} versus={item.delta.versus} />
        </div>
      ) : null}
    </>
  );

  const frame = cn(
    "block w-full rounded-md border bg-surface text-left",
    compact ? "px-3 py-2" : "p-3.5",
    item.active
      ? "border-primary bg-primary-subtle/30 ring-1 ring-primary"
      : "border-border",
  );

  if (!item.drill) return <div className={frame}>{body}</div>;
  const drill = item.drill;
  return (
    <button
      type="button"
      onClick={() => onDrill(drill)}
      aria-pressed={item.active}
      aria-label={`${item.label}: ${item.value}. ${item.context}.${deltaSpeech(item)} Show these employees.`}
      className={cn(
        frame,
        "transition-[transform,box-shadow,colors] duration-motion-fast hover:-translate-y-px hover:border-border-strong hover:bg-surface-secondary/60 hover:shadow-elevation-1 active:translate-y-0 active:scale-[0.985] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transform-none",
      )}
    >
      {body}
    </button>
  );
}

/** How many tiles are always visible; the rest sit behind "More". */
const ALWAYS_VISIBLE = 6;

/** KPI summary row. Each card is a drill-down button — it narrows the Who's In list below (and
 * the URL) to the matching employees; clicking the active card again clears the drill. Only the
 * six everyday figures are shown by default; the rarer ones (remote, overtime, half day, holiday…)
 * are one click away, and open by themselves while one of them is the active drill. */
export function KpiGrid({ kpi, filters, focusLabel, compare, onDrill }: KpiGridProps) {
  const { primary, secondary } = buildKpis(kpi, filters, focusLabel, compare);
  const visible = primary.slice(0, ALWAYS_VISIBLE);
  const more = [...primary.slice(ALWAYS_VISIBLE), ...secondary];
  const [expanded, setExpanded] = useState(false);
  const hasActiveMore = more.some((item) => item.active);
  const showMore = expanded || hasActiveMore;
  const moreWithData = more.filter((item) => item.count > 0).length;
  return (
    <section aria-label="Attendance summary" className="space-y-2.5">
      <div className="-mx-4 flex snap-x gap-2.5 overflow-x-auto px-4 pb-1 sm:mx-0 sm:grid sm:grid-cols-3 sm:overflow-visible sm:px-0 xl:grid-cols-6">
        {visible.map((item) => (
          <div key={item.key} className="min-w-[10rem] snap-start sm:min-w-0">
            <KpiCard item={item} onDrill={onDrill} />
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={() => setExpanded((open) => !open)}
        aria-expanded={showMore}
        disabled={hasActiveMore}
        className="inline-flex items-center gap-1 text-xs font-medium text-foreground-secondary hover:text-foreground disabled:cursor-default disabled:opacity-100"
      >
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", showMore && "rotate-180")} aria-hidden="true" />
        {showMore ? "Fewer statuses" : `More statuses${moreWithData > 0 ? ` (${moreWithData} with data)` : ""}`}
      </button>
      <Collapse open={showMore}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-7">
          {more.map((item) => (
            <KpiCard key={item.key} item={item} onDrill={onDrill} compact />
          ))}
        </div>
      </Collapse>
    </section>
  );
}
