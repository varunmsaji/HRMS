"use client";

import {
  ArrowRight,
  Banknote,
  BarChart3,
  CalendarCheck,
  CalendarDays,
  CalendarOff,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  ChevronRight,
  Clock,
  Gift,
  Activity,
  Users,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import {
  ActivityList,
  BirthdayList,
  CARD,
  DonutChart,
  Empty,
  GrowthChart,
  Panel,
  ViewAll,
  type DonutSegment,
} from "@/components/dashboard/dashboard-cards";
import {
  usePendingApprovals,
  type PendingApprovals,
} from "@/components/dashboard/use-pending-approvals";
import { useWorkforceOverview } from "@/components/dashboard/use-workforce-overview";
import { NativeSelect } from "@/components/ui/native-select";
import { useApiResource } from "@/hooks/use-api-resource";
import { usePermissions } from "@/lib/auth/use-permissions";
import { attendanceHref, type AttendanceOverview } from "@/lib/dashboard/overview";
import {
  insightsPath,
  periodLabel,
  relativeTime,
  trendOf,
  type CompanyDashboardInsights,
  type Trend,
} from "@/lib/dashboard/insights";
import { useEmployeeNames } from "@/lib/employee/use-employee-names";
import { cn } from "@/lib/utils";

interface Props {
  today: string;
}

// ---------------------------------------------------------------- KPI cards

function KpiCard({
  label,
  value,
  icon: Icon,
  tile,
  href,
  hint,
  trend,
}: {
  label: string;
  value: number | null;
  icon: LucideIcon;
  tile: string;
  href?: string;
  hint?: ReactNode;
  trend?: Trend | null;
}) {
  const body = (
    <>
      <span className={cn("flex h-11 w-11 items-center justify-center rounded-xl", tile)}>
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <p className="mt-4 text-sm text-foreground-secondary">{label}</p>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2">
        <p className="text-3xl font-bold tabular-nums tracking-tight text-foreground">
          {value === null ? "—" : value.toLocaleString()}
        </p>
        {trend ? (
          <p className="flex items-center gap-1 text-xs text-foreground-muted">
            <span
              className={cn(
                "inline-flex items-center font-semibold",
                trend.pct >= 0 ? "text-success" : "text-danger",
              )}
            >
              {trend.pct >= 0 ? (
                <ArrowUp className="h-3 w-3" aria-hidden="true" />
              ) : (
                <ArrowDown className="h-3 w-3" aria-hidden="true" />
              )}
              {trend.pct >= 0 ? "+" : ""}
              {trend.pct}%
            </span>
            {trend.label}
          </p>
        ) : null}
      </div>
      {hint ? <p className="mt-1 text-xs text-foreground-muted">{hint}</p> : null}
    </>
  );
  return href ? (
    <Link
      href={href}
      className={cn(CARD, "block transition-shadow hover:shadow-elevation-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring")}
    >
      {body}
    </Link>
  ) : (
    <div className={CARD}>{body}</div>
  );
}

// ------------------------------------------------------- attendance + leave

const ATTENDANCE_SEGMENTS = [
  { key: "present", label: "Present", stroke: "stroke-success", dot: "bg-success" },
  { key: "on_leave", label: "On leave", stroke: "stroke-on-leave", dot: "bg-on-leave" },
  { key: "absent", label: "Absent", stroke: "stroke-danger", dot: "bg-danger" },
  { key: "remote_work", label: "Work from home", stroke: "stroke-wfh", dot: "bg-wfh" },
  { key: "on_duty", label: "On duty", stroke: "stroke-info", dot: "bg-info" },
] as const;

function attendanceSegments(d: AttendanceOverview): DonutSegment[] {
  const known = ATTENDANCE_SEGMENTS.map((s) => ({ ...s, value: d[s.key] }));
  const others = Math.max(d.total - known.reduce((sum, s) => sum + s.value, 0), 0);
  return [
    ...known,
    { key: "others", label: "Others", stroke: "stroke-border-strong", dot: "bg-border-strong", value: others },
  ];
}

// Literal classes (Tailwind) assigned to leave types in the order the API returns them.
const LEAVE_COLOURS = [
  { stroke: "stroke-primary", dot: "bg-primary" },
  { stroke: "stroke-success", dot: "bg-success" },
  { stroke: "stroke-warning", dot: "bg-warning" },
  { stroke: "stroke-on-leave", dot: "bg-on-leave" },
  { stroke: "stroke-wfh", dot: "bg-wfh" },
  { stroke: "stroke-border-strong", dot: "bg-border-strong" },
];

// -------------------------------------------------------------- departments

function DepartmentBars({ data }: { data: AttendanceOverview }) {
  const rows = [...data.departments].sort((a, b) => b.total - a.total).slice(0, 6);
  const max = Math.max(...rows.map((r) => r.total), 1);
  if (rows.length === 0) return <Empty>No departments yet.</Empty>;
  return (
    <ul className="space-y-4">
      {rows.map((d) => (
        <li key={d.department_id ?? d.department_name} className="flex items-center gap-3 text-sm">
          <span className="w-28 shrink-0 truncate text-foreground-secondary">{d.department_name}</span>
          <span className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
            <span className="block h-full rounded-full bg-primary" style={{ width: `${(d.total / max) * 100}%` }} />
          </span>
          <span className="w-9 shrink-0 text-right font-semibold tabular-nums text-foreground">{d.total}</span>
        </li>
      ))}
    </ul>
  );
}

// -------------------------------------------------------- pending approvals

interface PendingRow {
  key: string;
  employeeId: string;
  title: string;
  at: string;
  href: string;
  tone: string;
  icon: LucideIcon;
}

function pendingRows(p: PendingApprovals | null): PendingRow[] {
  if (!p) return [];
  return [
    ...(p.leave?.items ?? []).map((i) => ({
      key: `l-${i.id}`,
      employeeId: i.employee_id,
      title: "Leave Request",
      at: i.submitted_at,
      href: "/app/leave-applications?status=SUBMITTED",
      tone: "bg-danger-subtle text-danger",
      icon: CalendarOff,
    })),
    ...(p.regularization?.items ?? []).map((i) => ({
      key: `r-${i.id}`,
      employeeId: i.employee_id,
      title: "Regularization",
      at: i.submitted_at,
      href: "/app/regularizations?status=SUBMITTED",
      tone: "bg-warning-subtle text-warning",
      icon: Clock,
    })),
    ...(p.overtime?.items ?? []).map((i) => ({
      key: `o-${i.id}`,
      employeeId: i.employee_id,
      title: "Overtime",
      at: i.created_at,
      href: "/app/overtime?status=PENDING",
      tone: "bg-info-subtle text-info",
      icon: CalendarCheck,
    })),
  ]
    .sort((a, b) => b.at.localeCompare(a.at))
    .slice(0, 4);
}

function PendingList({ data }: { data: PendingApprovals | null }) {
  const rows = useMemo(() => pendingRows(data), [data]);
  const names = useEmployeeNames(useMemo(() => rows.map((r) => r.employeeId), [rows]));
  if (rows.length === 0) return <Empty>Nothing pending.</Empty>;
  return (
    <ul className="space-y-4">
      {rows.map((r) => {
        const Icon = r.icon;
        return (
          <li key={r.key}>
            <Link href={r.href} className="flex items-center gap-3">
              <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", r.tone)}>
                <Icon className="h-4 w-4" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-foreground">{r.title}</span>
                <span className="block truncate text-xs text-foreground-muted">
                  {names(r.employeeId) ?? "Employee"}
                </span>
              </span>
              <span className="shrink-0 text-2xs text-foreground-muted">{relativeTime(r.at)}</span>
              <ChevronRight className="h-4 w-4 shrink-0 text-foreground-muted" aria-hidden="true" />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

// ------------------------------------------------------------ action tiles

interface Tile {
  href: string;
  title: string;
  body: string;
  icon: LucideIcon;
  anyOf: string[];
}

const TILES: Tile[] = [
  { href: "/app/employees", title: "Manage Employees", body: "Add, update and manage your workforce.", icon: Users, anyOf: ["EMPLOYEE.VIEW_ALL", "EMPLOYEE.CREATE"] },
  { href: "/app/attendance", title: "Track Attendance", body: "Monitor attendance and working hours.", icon: CalendarCheck, anyOf: ["ATTENDANCE.VIEW"] },
  { href: "/app/payroll/pay-runs", title: "Process Payroll", body: "Run payroll and generate payslips.", icon: Banknote, anyOf: ["PAYROLL.RUN_VIEW", "PAYROLL.RUN_PROCESS"] },
  { href: "/app/attendance", title: "View Reports", body: "Access detailed reports and analytics.", icon: BarChart3, anyOf: ["ATTENDANCE.VIEW"] },
];

const TILE_STYLE = [
  "bg-gradient-to-br from-blue-600 to-blue-700 text-white",
  "bg-gradient-to-br from-cyan-500 to-sky-500 text-white",
  "border border-border bg-surface text-foreground",
  "border border-border bg-surface text-foreground",
];

function ActionTiles() {
  const { canAny } = usePermissions();
  const tiles = TILES.filter((t) => canAny(t.anyOf));
  if (tiles.length === 0) return null;
  return (
    <section aria-label="Shortcuts" className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
      {tiles.map((t, i) => {
        const Icon = t.icon;
        const filled = i < 2;
        return (
          <Link
            key={t.title}
            href={t.href}
            className={cn(
              "flex items-center gap-4 rounded-2xl p-5 shadow-elevation-1 transition-shadow hover:shadow-elevation-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              TILE_STYLE[i],
            )}
          >
            <span
              className={cn(
                "flex h-12 w-12 shrink-0 items-center justify-center rounded-xl",
                filled ? "bg-white/20" : "bg-primary-subtle text-primary",
              )}
            >
              <Icon className="h-5 w-5" aria-hidden="true" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold">{t.title}</span>
              <span className={cn("mt-0.5 block text-xs", filled ? "text-white/80" : "text-foreground-muted")}>
                {t.body}
              </span>
            </span>
            <span
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                filled ? "bg-white/20" : "border border-border",
              )}
            >
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </span>
          </Link>
        );
      })}
    </section>
  );
}

// ------------------------------------------------------------------- page

/** The company dashboard body. Every figure is the backend's — attendance overview, pending queue
 * totals and `/dashboards/company/insights`; a card whose source the viewer can't read is omitted
 * rather than shown as zero. */
export function DashboardOverview({ today }: Props) {
  const { can } = usePermissions();
  const canAttendance = can("ATTENDANCE.VIEW");
  const canLeave = can("LEAVE.APPLICATION_APPROVE");
  const canReg = can("ATTENDANCE.REGULARIZATION_APPROVE");
  const canOt = can("ATTENDANCE.OVERTIME_APPROVE");
  const canOnboarding = can("ONBOARDING.REVIEW") && can("ONBOARDING.VIEW");
  const canPending = canLeave || canReg || canOt || canOnboarding;

  const [growthMonths, setGrowthMonths] = useState(6);
  const [leaveScope, setLeaveScope] = useState<"month" | "year">("month");

  const overview = useWorkforceOverview({ date: "", departmentId: "", branchId: "", enabled: canAttendance });
  const pending = usePendingApprovals({
    leave: canLeave,
    regularization: canReg,
    overtime: canOt,
    onboarding: canOnboarding,
  });
  const insights = useApiResource<CompanyDashboardInsights>(insightsPath(growthMonths, leaveScope));

  const d = overview.data;
  const ins = insights.data;
  const pendingTotal = pending.data
    ? (pending.data.leave?.total ?? 0) +
      (pending.data.regularization?.total ?? 0) +
      (pending.data.overtime?.total ?? 0) +
      (pending.data.onboardingHr?.total ?? 0) +
      (pending.data.onboardingCandidate?.total ?? 0)
    : null;
  const pendingHint = pending.data
    ? [
        pending.data.leave ? `${pending.data.leave.total} Leave` : null,
        pending.data.regularization ? `${pending.data.regularization.total} Attendance` : null,
        pending.data.overtime ? `${pending.data.overtime.total} Overtime` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : undefined;

  const leaveSegments: DonutSegment[] = (ins?.leave_statistics.by_type ?? []).map((t, i) => ({
    key: t.leave_type_id,
    label: t.name.replace(/ Leave$/, ""),
    value: t.days,
    ...LEAVE_COLOURS[Math.min(i, LEAVE_COLOURS.length - 1)],
  }));

  const select = "h-8 w-auto py-0 text-xs";

  const cmp = ins?.kpi_comparison;
  const headcountTrend = trendOf(d?.total, cmp?.headcount_prev_month_end, "vs last month");
  const presentTrend = trendOf(d?.present, cmp?.yesterday_present, "vs yesterday");
  const onLeaveTrend = trendOf(d?.on_leave, cmp?.yesterday_on_leave, "vs yesterday");

  return (
    <div className="space-y-5">
      {ins ? (
        <div className="flex justify-end">
          <span
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm font-medium text-foreground shadow-elevation-1"
            title="Period covered by the leave statistics card"
          >
            <CalendarDays className="h-4 w-4 text-primary" aria-hidden="true" />
            {periodLabel(ins.leave_statistics.period_start, ins.leave_statistics.period_end)}
          </span>
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {canAttendance ? (
          <>
            <KpiCard
              label="Total Employees"
              value={d?.total ?? null}
              icon={Users}
              tile="bg-primary-subtle text-primary"
              href="/app/employees"
              trend={headcountTrend}
              hint={d ? `${d.expected_employees} expected to work today` : undefined}
            />
            <KpiCard
              label="Present Today"
              value={d?.present ?? null}
              icon={CheckCircle2}
              tile="bg-success-subtle text-success"
              href={attendanceHref("present", d?.attendance_date ?? today, today)}
              trend={presentTrend}
              hint={d?.late ? `${d.late} late arrivals` : undefined}
            />
            <KpiCard
              label="On Leave Today"
              value={d?.on_leave ?? null}
              icon={CalendarOff}
              tile="bg-warning-subtle text-warning"
              href={attendanceHref("on_leave", d?.attendance_date ?? today, today)}
              trend={onLeaveTrend}
              hint={d?.half_day_leave ? `${d.half_day_leave} half-day` : undefined}
            />
          </>
        ) : null}
        {canPending ? (
          <KpiCard label="Pending Approvals" value={pendingTotal} icon={Clock} tile="bg-info-subtle text-info" hint={pendingHint} />
        ) : null}
      </div>

      <div className="grid min-w-0 gap-5 lg:grid-cols-2 xl:grid-cols-3">
        <Panel
          title="Employee Growth"
          icon={<Users className="h-4 w-4" aria-hidden="true" />}
          action={
            <NativeSelect
              value={growthMonths}
              onChange={(e) => setGrowthMonths(Number(e.target.value))}
              className={select}
              aria-label="Growth period"
            >
              <option value={6}>Last 6 months</option>
              <option value={12}>Last 12 months</option>
            </NativeSelect>
          }
        >
          {ins ? <GrowthChart points={ins.headcount_trend} /> : <Empty>{insights.error ? "Couldn't load." : "Loading…"}</Empty>}
        </Panel>

        {canAttendance ? (
          <Panel title="Attendance Overview" icon={<Activity className="h-4 w-4" aria-hidden="true" />} action={<ViewAll href="/app/attendance" />}>
            {d ? <DonutChart segments={attendanceSegments(d)} total={d.total} ariaLabel="Attendance distribution" /> : <Empty>Loading…</Empty>}
          </Panel>
        ) : null}

        <Panel
          title="Leave Statistics"
          icon={<CalendarDays className="h-4 w-4" aria-hidden="true" />}
          action={
            <NativeSelect
              value={leaveScope}
              onChange={(e) => setLeaveScope(e.target.value as "month" | "year")}
              className={select}
              aria-label="Leave period"
            >
              <option value="month">This Month</option>
              <option value="year">This Year</option>
            </NativeSelect>
          }
        >
          {ins ? (
            leaveSegments.length > 0 ? (
              <DonutChart segments={leaveSegments} total={ins.leave_statistics.total_days} ariaLabel="Approved leave days by type" />
            ) : (
              <Empty>No approved leave in this period.</Empty>
            )
          ) : (
            <Empty>{insights.error ? "Couldn't load." : "Loading…"}</Empty>
          )}
        </Panel>
      </div>

      <div className="grid min-w-0 gap-5 lg:grid-cols-2 xl:grid-cols-4">
        <Panel title="Upcoming Birthdays" icon={<Gift className="h-4 w-4" aria-hidden="true" />}>
          {ins ? <BirthdayList items={ins.upcoming_birthdays} /> : <Empty>Loading…</Empty>}
        </Panel>

        {canPending ? (
          <Panel title="Pending Approvals" icon={<Clock className="h-4 w-4" aria-hidden="true" />} action={<ViewAll href="/app/leave-applications?status=SUBMITTED" />}>
            <PendingList data={pending.data} />
          </Panel>
        ) : null}

        {canAttendance ? (
          <Panel title="Department Overview" action={<ViewAll href="/app/departments" />}>
            {d ? <DepartmentBars data={d} /> : <Empty>Loading…</Empty>}
          </Panel>
        ) : null}

        <Panel title="Recent Activities" icon={<Activity className="h-4 w-4" aria-hidden="true" />}>
          {ins ? <ActivityList items={ins.recent_activities} /> : <Empty>Loading…</Empty>}
        </Panel>
      </div>

      <ActionTiles />
    </div>
  );
}
