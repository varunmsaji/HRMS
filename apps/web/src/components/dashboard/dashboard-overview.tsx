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
import { splitEmployeeLabel } from "@/components/employee/employee-identity";
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
  { key: "remote_work", label: "WFH", stroke: "stroke-wfh", dot: "bg-wfh" },
  { key: "on_duty", label: "On duty", stroke: "stroke-info", dot: "bg-info" },
] as const;

/** True when none of the tracked statuses has anyone in it, so a donut would be one grey ring. */
function nobodyRecorded(d: AttendanceOverview): boolean {
  return ATTENDANCE_SEGMENTS.every((s) => d[s.key] === 0);
}

function NoCheckIns({ data }: { data: AttendanceOverview }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 py-6 text-center">
      <span className="flex h-11 w-11 items-center justify-center rounded-full bg-muted text-foreground-muted">
        <Activity className="h-5 w-5" aria-hidden="true" />
      </span>
      <p className="text-sm font-medium text-foreground">No check-ins recorded yet</p>
      <p className="text-xs text-foreground-muted">
        {data.total} employees · {data.expected_employees} expected to work today
      </p>
    </div>
  );
}

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
        <li key={d.department_id ?? d.department_name}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate text-foreground-secondary" title={d.department_name}>
              {d.department_name}
            </span>
            <span className="shrink-0 font-semibold tabular-nums text-foreground">{d.total}</span>
          </div>
          <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-muted">
            <span className="block h-full rounded-full bg-primary" style={{ width: `${(d.total / max) * 100}%` }} />
          </span>
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
                  {splitEmployeeLabel(names(r.employeeId) ?? "Employee").name} · {relativeTime(r.at)}
                </span>
              </span>
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

// One treatment for all four shortcuts; the colour lives in the icon tile only.
const TILE_TONE = [
  "bg-primary-subtle text-primary",
  "bg-info-subtle text-info",
  "bg-success-subtle text-success",
  "bg-warning-subtle text-warning",
];

function ActionTiles() {
  const { canAny } = usePermissions();
  const tiles = TILES.filter((t) => canAny(t.anyOf));
  if (tiles.length === 0) return null;
  return (
    <section aria-label="Shortcuts" className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
      {tiles.map((t, i) => {
        const Icon = t.icon;
        return (
          <Link
            key={t.title}
            href={t.href}
            className="group flex items-center gap-4 rounded-2xl border border-border bg-surface p-5 shadow-elevation-1 transition-all duration-motion-base hover:-translate-y-0.5 hover:border-border-strong hover:shadow-elevation-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className={cn("flex h-12 w-12 shrink-0 items-center justify-center rounded-xl", TILE_TONE[i % TILE_TONE.length])}>
              <Icon className="h-5 w-5" aria-hidden="true" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold text-foreground">{t.title}</span>
              <span className="mt-0.5 block text-xs text-foreground-muted">{t.body}</span>
            </span>
            <ArrowRight
              className="h-4 w-4 shrink-0 text-foreground-muted transition-transform duration-motion-fast group-hover:translate-x-0.5 group-hover:text-primary"
              aria-hidden="true"
            />
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
          <KpiCard label="Pending Approvals" value={pendingTotal} icon={Clock} tile="bg-info-subtle text-info" href="/app/leave-applications?status=SUBMITTED" hint={pendingHint} />
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
            {d ? (
              nobodyRecorded(d) ? (
                <NoCheckIns data={d} />
              ) : (
                <DonutChart segments={attendanceSegments(d)} total={d.total} ariaLabel="Attendance distribution" />
              )
            ) : (
              <Empty>Loading…</Empty>
            )}
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
