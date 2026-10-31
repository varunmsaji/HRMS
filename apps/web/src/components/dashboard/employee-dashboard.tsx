"use client";

import {
  ArrowRight,
  Banknote,
  CalendarCheck,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  Clock,
  FileText,
  Hourglass,
  Palmtree,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import { PunchEntryDialog } from "@/components/attendance/punch-entry-dialog";
import { useSection, type Section } from "@/components/attendance/dashboard/use-dashboard-data";
import { CARD, DonutChart, Empty, Panel, ViewAll } from "@/components/dashboard/dashboard-cards";
import { apiClient } from "@/lib/api/client";
import { addDays, monthStart, weekStart } from "@/lib/attendance/dashboard";
import type { AttendanceDay } from "@/lib/attendance/types";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import { relativeTime } from "@/lib/dashboard/insights";
import {
  clock,
  duration,
  leaveRange,
  longDate,
  punchState,
  shortDay,
  sumBalances,
  summariseMonth,
  trimNumber,
  weekBars,
} from "@/lib/dashboard/employee";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import type { Assignment, Employee } from "@/lib/employee/types";
import type { LeaveApplication } from "@/lib/leave-application/types";
import type { LeaveBalance } from "@/lib/leave-ledger/types";
import { formatInr, formatPayMonth, type PayslipSummary } from "@/lib/payroll/types";
import { REGULARIZATION_TYPE_LABELS, type RegularizationRequest } from "@/lib/regularization/types";
import { cn } from "@/lib/utils";

interface Props {
  employeeId: string;
  today: string;
  timezone: string;
}

const LEAVE_COLOURS = [
  { stroke: "stroke-primary", dot: "bg-primary" },
  { stroke: "stroke-success", dot: "bg-success" },
  { stroke: "stroke-warning", dot: "bg-warning" },
  { stroke: "stroke-on-leave", dot: "bg-on-leave" },
  { stroke: "stroke-wfh", dot: "bg-wfh" },
  { stroke: "stroke-border-strong", dot: "bg-border-strong" },
];

const STATUS_PILL: Record<string, string> = {
  SUBMITTED: "bg-warning-subtle text-warning",
  APPROVED: "bg-success-subtle text-success",
  REJECTED: "bg-danger-subtle text-danger",
  CANCELLED: "bg-muted text-foreground-muted",
};

function Pill({ tone, children }: { tone: string; children: ReactNode }) {
  return (
    <span className={cn("shrink-0 rounded-full px-2.5 py-1 text-2xs font-semibold", tone)}>{children}</span>
  );
}

/** Renders a section's body once ready, else its own loading / error line — one broken request
 * never blanks the rest of the dashboard. */
function Body<T>({
  section,
  label,
  children,
}: {
  section: Section<T>;
  label: string;
  children: (data: T) => ReactNode;
}) {
  if (section.status === "error") {
    return (
      <p className="py-6 text-center text-sm text-foreground-muted">
        {label} couldn&apos;t be loaded.{" "}
        <button type="button" onClick={section.retry} className="font-medium text-primary hover:underline">
          Retry
        </button>
      </p>
    );
  }
  if (section.status !== "ready" || section.data === null) {
    return <div className="h-32 animate-pulse rounded-xl bg-muted" role="status" aria-label={`Loading ${label}`} />;
  }
  return <>{children(section.data)}</>;
}

function StatCard({
  icon: Icon,
  tile,
  label,
  value,
  hint,
}: {
  icon: LucideIcon;
  tile: string;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className={CARD}>
      <span className={cn("flex h-11 w-11 items-center justify-center rounded-full", tile)}>
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <p className="mt-4 text-2xs font-semibold uppercase tracking-wider text-foreground-muted">{label}</p>
      <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">{value}</p>
      <p className="mt-1 truncate text-xs text-foreground-muted">{hint}</p>
    </div>
  );
}

function ActionTile({
  title,
  body,
  icon: Icon,
  href,
  onClick,
  tone,
}: {
  title: string;
  body: string;
  icon: LucideIcon;
  href?: string;
  onClick?: () => void;
  tone: "navy" | "teal" | "plain";
}) {
  const filled = tone !== "plain";
  const cls = cn(
    "relative flex h-full min-h-[11rem] w-full flex-col justify-between overflow-hidden rounded-2xl p-5 text-left shadow-elevation-1 transition-shadow hover:shadow-elevation-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
    tone === "navy" && "bg-gradient-to-br from-[#0b1d4d] to-[#1e3a8a] text-white",
    tone === "teal" && "bg-gradient-to-br from-[#075985] to-[#0284c7] text-white",
    tone === "plain" && "border border-border bg-surface text-foreground",
  );
  const inner = (
    <>
      <div>
        <p className="text-lg font-bold">{title}</p>
        <p className={cn("mt-1 text-xs", filled ? "text-white/80" : "text-foreground-muted")}>{body}</p>
      </div>
      <span
        className={cn(
          "ml-auto flex h-10 w-10 items-center justify-center rounded-full",
          filled ? "bg-white/20" : "bg-muted text-foreground",
        )}
      >
        <ArrowRight className="h-4 w-4" aria-hidden="true" />
        <Icon className="sr-only" aria-hidden="true" />
      </span>
    </>
  );
  return href ? (
    <Link href={href} className={cls}>
      {inner}
    </Link>
  ) : (
    <button type="button" onClick={onClick} className={cls}>
      {inner}
    </button>
  );
}

export function EmployeeDashboard({ employeeId, today, timezone }: Props) {
  const { user } = useAuth();
  const { can } = usePermissions();
  const datePattern = useCompanyDatePattern();
  const [punchOpen, setPunchOpen] = useState(false);

  const from = useMemo(() => {
    const month = monthStart(today);
    const week = weekStart(today);
    return week < month ? week : month;
  }, [today]);

  const employee = useSection<Employee>(
    () => apiClient.get<Employee>(`/employees/${employeeId}`),
    `emp|${employeeId}`,
    true,
  );
  const assignments = useSection<Assignment[]>(
    () => apiClient.get<Assignment[]>(`/employees/${employeeId}/assignments`),
    `assign|${employeeId}`,
    true,
  );
  const current = assignments.data?.find((a) => a.effective_to === null) ?? null;
  // Subtitle extras are best-effort: a lookup the viewer can't read just drops that part.
  const designation = useSection<Designation>(
    () => apiClient.get<Designation>(`/designations/${current?.designation_id}`),
    `desig|${current?.designation_id}`,
    Boolean(current?.designation_id),
  );
  const department = useSection<Department>(
    () => apiClient.get<Department>(`/departments/${current?.department_id}`),
    `dept|${current?.department_id}`,
    Boolean(current?.department_id),
  );
  const days = useSection<AttendanceDay[]>(
    () =>
      apiClient.get<AttendanceDay[]>(
        `/attendance/days?${new URLSearchParams({ employee_id: employeeId, date_from: from, date_to: today }).toString()}`,
      ),
    `days|${employeeId}|${from}|${today}`,
    true,
  );
  const balances = useSection<LeaveBalance[]>(
    () => apiClient.get<LeaveBalance[]>(`/leave-balances?employee_id=${employeeId}`),
    `bal|${employeeId}`,
    true,
  );
  const leaves = useSection<LeaveApplication[]>(
    () => apiClient.get<LeaveApplication[]>(`/leave-applications?employee_id=${employeeId}`),
    `leave|${employeeId}`,
    true,
  );
  const regs = useSection<RegularizationRequest[]>(
    () => apiClient.get<RegularizationRequest[]>(`/regularizations?${new URLSearchParams({ employee_id: employeeId }).toString()}`),
    `regs|${employeeId}`,
    true,
  );
  const payslips = useSection<PayslipSummary[]>(() => apiClient.get<PayslipSummary[]>("/me/payslips"), "payslips", true);

  const monthPrefix = today.slice(0, 7);
  const monthDays = useMemo(
    () => (days.data ?? []).filter((d) => d.attendance_date.startsWith(monthPrefix)),
    [days.data, monthPrefix],
  );
  const todayRow = days.data?.find((d) => d.attendance_date === today) ?? null;
  const state = punchState(todayRow);
  const bars = useMemo(() => weekBars(days.data ?? [], today), [days.data, today]);
  const month = useMemo(() => summariseMonth(monthDays), [monthDays]);

  const submittedLeaves = (leaves.data ?? []).filter((l) => l.status === "SUBMITTED");
  const submittedRegs = (regs.data ?? []).filter((r) => r.status === "SUBMITTED");
  const waiting = submittedLeaves.length + submittedRegs.length;
  const leaveNames = new Map((balances.data ?? []).map((b) => [b.leave_type_id, b.leave_type_name]));

  const name = employee.data ? (employee.data.display_name ?? employee.data.first_name) : "";
  const leaveTotal = sumBalances(balances.data ?? []);
  const fmtDate = (iso: string) => formatCompanyDate(iso, datePattern);

  const actionable = [
    ...submittedLeaves.map((l) => ({
      key: `l-${l.id}`,
      icon: Palmtree,
      title: "Leave request",
      detail: leaveRange(l.start_date, l.end_date, l.total_days),
      at: l.submitted_at,
      href: `/app/leave-applications/${l.id}`,
    })),
    ...submittedRegs.map((r) => ({
      key: `r-${r.id}`,
      icon: CalendarClock,
      title: "Attendance correction",
      detail: `${REGULARIZATION_TYPE_LABELS[r.request_type] ?? r.request_type} · ${shortDay(r.attendance_date)}`,
      at: r.submitted_at,
      href: `/app/regularizations/${r.id}`,
    })),
  ]
    .sort((a, b) => b.at.localeCompare(a.at))
    .slice(0, 3);

  const recentLeaves = [...(leaves.data ?? [])].sort((a, b) => b.submitted_at.localeCompare(a.submitted_at)).slice(0, 3);
  const recentDays = [...(days.data ?? [])]
    .filter((d) => d.actual_first_in || d.missing_punch)
    .sort((a, b) => b.attendance_date.localeCompare(a.attendance_date))
    .slice(0, 3);
  const latestPayslip = [...(payslips.data ?? [])].sort((a, b) => b.pay_date.localeCompare(a.pay_date))[0] ?? null;

  const weekMax = Math.max(8, ...bars.map((b) => b.hours));

  return (
    <div className="space-y-6">
      <section aria-label="Welcome" className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Dashboard</h1>
          <p className="mt-1.5 text-sm text-foreground-secondary">
            Here&apos;s your workday{name ? `, ${name}` : ""}.
          </p>
          {employee.data ? (
            <p className="mt-0.5 text-xs text-foreground-muted">
              {[employee.data.employee_code, designation.data?.title, department.data?.name].filter(Boolean).join(" · ")}
            </p>
          ) : null}
        </div>
        <span className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface px-4 py-2 text-sm font-medium text-foreground shadow-elevation-1">
          <CalendarCheck className="h-4 w-4 text-primary" aria-hidden="true" />
          {longDate(today)}
        </span>
      </section>

      <section aria-label="Summary" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={CheckCircle2}
          tile="bg-success-subtle text-success"
          label="Today's status"
          value={state === "in" ? "Punched in" : state === "out" ? "Punched out" : days.status === "ready" ? "Not punched in" : "—"}
          hint={
            state === "none"
              ? "No punch recorded yet"
              : state === "in"
                ? `Since ${clock(todayRow?.actual_first_in, timezone)}`
                : `Out at ${clock(todayRow?.actual_last_out, timezone)}`
          }
        />
        <StatCard
          icon={Clock}
          tile="bg-info-subtle text-info"
          label="Worked today"
          value={todayRow?.actual_first_in ? duration(todayRow.worked_minutes) : "—"}
          hint={todayRow?.actual_first_in ? `First in ${clock(todayRow.actual_first_in, timezone)}` : "Starts with your first punch"}
        />
        <StatCard
          icon={Palmtree}
          tile="bg-warning-subtle text-warning"
          label="Leave left"
          value={balances.status === "ready" ? trimNumber(leaveTotal) : "—"}
          hint={(balances.data ?? [])
            .slice(0, 3)
            .map((b) => `${b.leave_type_name} ${trimNumber(Number(b.balance))}`)
            .join(" · ")}
        />
        <StatCard
          icon={Hourglass}
          tile="bg-primary-subtle text-primary"
          label="Waiting on HR"
          value={leaves.status === "ready" && regs.status === "ready" ? String(waiting) : "—"}
          hint={`${submittedLeaves.length} leave · ${submittedRegs.length} correction`}
        />
      </section>

      <section aria-label="Insights" className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel title="Hours this week" action={<span className="text-xs text-foreground-muted">Worked hours, Mon–Sun</span>}>
          <Body section={days} label="Hours">
            {() => (
              <div className="flex h-56 gap-3" role="img" aria-label="Worked hours per day this week">
                <div className="flex flex-col justify-between pb-6 text-right text-2xs tabular-nums text-foreground-muted">
                  {[1, 0.75, 0.5, 0.25, 0].map((f) => (
                    <span key={f}>{Math.round(weekMax * f * 10) / 10}h</span>
                  ))}
                </div>
                <div className="flex min-w-0 flex-1 items-end justify-between gap-2 border-b border-border pb-6">
                  {bars.map((b) => {
                    const isToday = b.date === today;
                    return (
                      <div key={b.date} className="relative flex h-full min-w-0 flex-1 flex-col justify-end">
                        {b.hours > 0 ? (
                          <span className="mb-1 text-center text-2xs font-medium tabular-nums text-foreground-secondary">
                            {b.hours}h
                          </span>
                        ) : null}
                        <div
                          className={cn("w-full rounded-t-md", isToday ? "bg-sky-400" : "bg-blue-700/90", b.hours === 0 && "bg-muted")}
                          style={{ height: `${Math.max((b.hours / weekMax) * 85, b.hours === 0 ? 1 : 3)}%` }}
                        />
                        <span
                          className={cn(
                            "absolute -bottom-6 left-0 right-0 text-center text-2xs",
                            isToday ? "font-semibold text-foreground" : "text-foreground-muted",
                          )}
                        >
                          {b.label}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </Body>
        </Panel>

        <Panel
          title="Attendance this month"
          action={<span className="text-xs text-foreground-muted">{new Date(`${today}T00:00:00Z`).toLocaleString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" })}</span>}
        >
          <Body section={days} label="Attendance">
            {() => (
              <>
                <DonutChart
                  ariaLabel="Attendance days this month"
                  centerLabel="Days"
                  total={month.total}
                  segments={[
                    { key: "present", label: "Present", value: month.counts.present, stroke: "stroke-success", dot: "bg-success" },
                    { key: "on_leave", label: "On leave", value: month.counts.on_leave, stroke: "stroke-on-leave", dot: "bg-on-leave" },
                    { key: "absent", label: "Absent", value: month.counts.absent, stroke: "stroke-danger", dot: "bg-danger" },
                    { key: "other", label: "Other", value: month.counts.other, stroke: "stroke-info", dot: "bg-info" },
                  ]}
                />
                <p className="mt-4 text-xs text-foreground-muted">
                  {month.weeklyOffs} weekly {month.weeklyOffs === 1 ? "off" : "offs"} · {month.holidays}{" "}
                  {month.holidays === 1 ? "holiday" : "holidays"}
                </p>
              </>
            )}
          </Body>
        </Panel>

        <Panel title="Leave balances" action={<span className="text-xs text-foreground-muted">Days remaining</span>}>
          <Body section={balances} label="Leave balances">
            {(rows) =>
              rows.length === 0 ? (
                <Empty>No leave balances yet.</Empty>
              ) : (
                <DonutChart
                  ariaLabel="Leave balances by type"
                  centerLabel="Days"
                  total={Math.round(sumBalances(rows) * 10) / 10}
                  segments={rows.map((b, i) => ({
                    key: b.leave_type_id,
                    label: b.leave_type_name,
                    value: Number(b.balance) || 0,
                    ...LEAVE_COLOURS[i % LEAVE_COLOURS.length],
                  }))}
                />
              )
            }
          </Body>
        </Panel>
      </section>

      <section aria-label="Activity" className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Panel title="Needs attention" action={<ViewAll href="/app/leave-applications" />}>
          {leaves.status === "ready" && regs.status === "ready" ? (
            actionable.length === 0 ? (
              <Empty>Nothing needs your attention.</Empty>
            ) : (
              <ul className="space-y-3">
                {actionable.map((a) => (
                  <li key={a.key}>
                    <Link
                      href={a.href}
                      className="flex items-center gap-3 rounded-xl bg-primary-subtle/60 p-3 hover:bg-primary-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface text-primary">
                        <a.icon className="h-4 w-4" aria-hidden="true" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold text-foreground">{a.title}</span>
                        <span className="block truncate text-xs text-foreground-muted">{a.detail}</span>
                        <span className="block text-2xs font-semibold text-warning">Submitted · {relativeTime(a.at)}</span>
                      </span>
                      <ChevronRight className="h-4 w-4 shrink-0 text-foreground-muted" aria-hidden="true" />
                    </Link>
                  </li>
                ))}
              </ul>
            )
          ) : (
            <Body section={{ ...leaves, status: leaves.status === "error" || regs.status === "error" ? "error" : "loading", retry: () => { leaves.retry(); regs.retry(); } }} label="Requests">
              {() => null}
            </Body>
          )}
        </Panel>

        <Panel title="Recent leave" action={<ViewAll href="/app/leave-applications" />}>
          <Body section={leaves} label="Leave">
            {() =>
              recentLeaves.length === 0 ? (
                <Empty>No leave applied yet.</Empty>
              ) : (
                <ul className="space-y-4">
                  {recentLeaves.map((l) => (
                    <li key={l.id} className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-foreground">
                          {leaveNames.get(l.leave_type_id) ?? "Leave"}
                        </p>
                        <p className="truncate text-xs text-foreground-muted">{leaveRange(l.start_date, l.end_date, l.total_days)}</p>
                      </div>
                      <Pill tone={STATUS_PILL[l.status] ?? STATUS_PILL.CANCELLED}>
                        {l.status.charAt(0) + l.status.slice(1).toLowerCase()}
                      </Pill>
                    </li>
                  ))}
                </ul>
              )
            }
          </Body>
        </Panel>

        <Panel title="Recent days" action={<ViewAll href="/app/attendance" />}>
          <Body section={days} label="Recent days">
            {() =>
              recentDays.length === 0 ? (
                <Empty>No attendance recorded yet.</Empty>
              ) : (
                <ul className="space-y-4">
                  {recentDays.map((d) => {
                    const incomplete = d.missing_punch || (d.actual_first_in && !d.actual_last_out && d.attendance_date !== today);
                    return (
                      <li key={d.id} className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-foreground">{shortDay(d.attendance_date)}</p>
                          <p className="text-xs tabular-nums text-foreground-muted">
                            {clock(d.actual_first_in, timezone)}–{clock(d.actual_last_out, timezone)}
                          </p>
                          {incomplete ? <p className="text-2xs font-medium text-danger">Missing punch out</p> : null}
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1">
                          <Pill tone={incomplete ? "bg-danger-subtle text-danger" : "bg-success-subtle text-success"}>
                            {incomplete ? "Incomplete" : "Present"}
                          </Pill>
                          <span className="text-xs font-semibold tabular-nums text-foreground">
                            {d.actual_first_in ? duration(d.worked_minutes) : "—"}
                          </span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )
            }
          </Body>
        </Panel>

        <Panel
          title="Latest payslip"
          action={<FileText className="h-4 w-4 text-primary" aria-hidden="true" />}
        >
          <Body section={payslips} label="Payslip">
            {() =>
              latestPayslip ? (
                <div className="flex h-full flex-col">
                  <p className="text-xl font-bold text-foreground">{formatPayMonth(latestPayslip.month)}</p>
                  <p className="mt-0.5 text-xs text-foreground-muted">Paid on {fmtDate(latestPayslip.pay_date)}</p>
                  <p className="mt-4 text-xs text-foreground-muted">Net pay</p>
                  <p className="text-3xl font-bold tabular-nums text-foreground">{formatInr(latestPayslip.net_minor)}</p>
                  <Link
                    href={`/app/me/payslips/${latestPayslip.pay_run_id}`}
                    className="mt-auto inline-flex items-center gap-1.5 pt-6 text-sm font-medium text-primary hover:underline"
                  >
                    Open payslip <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </Link>
                </div>
              ) : (
                <Empty>No payslips yet.</Empty>
              )
            }
          </Body>
        </Panel>
      </section>

      <section aria-label="Quick actions" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <ActionTile
          tone="navy"
          icon={Clock}
          title={state === "in" ? "Punch out" : "Punch in"}
          body={
            state === "in"
              ? `You punched in at ${clock(todayRow?.actual_first_in, timezone)}. Punch out when you finish.`
              : "Record the start of your workday."
          }
          {...(can("ATTENDANCE.PUNCH") ? { onClick: () => setPunchOpen(true) } : { href: "/app/attendance" })}
        />
        <ActionTile tone="teal" icon={Palmtree} title="Apply for leave" body="Request casual, sick, or earned leave." href="/app/leave-applications" />
        <ActionTile tone="plain" icon={CalendarClock} title="Request a correction" body="Fix a missing or wrong punch." href="/app/regularizations" />
        <ActionTile tone="plain" icon={Banknote} title="View payslips" body="Open this month's slip and older slips." href="/app/me/payslips" />
      </section>

      <PunchEntryDialog
        open={punchOpen}
        onOpenChange={setPunchOpen}
        employeeId={employeeId}
        employeeLabel={name || user?.email || undefined}
        onRecorded={() => days.retry()}
      />
    </div>
  );
}
