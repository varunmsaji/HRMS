"use client";

import { CalendarClock } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AbsenceInsights } from "@/components/attendance/dashboard/absence-insights";
import { BreakdownPanel } from "@/components/attendance/dashboard/breakdown-panel";
import { AttendanceDashboardSkeleton } from "@/components/attendance/dashboard/dashboard-skeleton";
import { PunctualityPanel, WeekdayPanel } from "@/components/attendance/dashboard/insight-panels";
import { KpiGrid } from "@/components/attendance/dashboard/kpi-grid";
import { MusterHeatmap } from "@/components/attendance/dashboard/muster-heatmap";
import { NeedsAttention } from "@/components/attendance/dashboard/needs-attention";
import { OvertimePanel } from "@/components/attendance/dashboard/overtime-panel";
import { PayrollReadiness } from "@/components/attendance/dashboard/payroll-readiness";
import { MonthlySummary, PeriodStatus } from "@/components/attendance/dashboard/period-status";
import { ReportsPanel } from "@/components/attendance/dashboard/reports-panel";
import { SectionCard } from "@/components/attendance/dashboard/section-card";
import { SelfView } from "@/components/attendance/dashboard/self-view";
import { StatusChart } from "@/components/attendance/dashboard/status-chart";
import { AttendanceToolbar } from "@/components/attendance/dashboard/toolbar";
import { TodayPulse } from "@/components/attendance/dashboard/today-pulse";
import { TrendChart } from "@/components/attendance/dashboard/trend-chart";
import { useDashboardData, useDirectoryDetails } from "@/components/attendance/dashboard/use-dashboard-data";
import { WhosInPanel, type WhosInRow } from "@/components/attendance/dashboard/whos-in-panel";
import { WorkHoursPanel } from "@/components/attendance/dashboard/work-hours-panel";
import { PunchEntryDialog } from "@/components/attendance/punch-entry-dialog";
import { ErrorState } from "@/components/common/error-state";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import {
  BUCKET_LABELS,
  DEFAULT_FILTERS,
  FLAG_LABELS,
  applyDrillFilters,
  applyPopulationFilters,
  buildAttentionItems,
  buildMuster,
  dailyHours,
  employeesWithoutRecord,
  formatShortDate,
  indexEmployees,
  musterDates,
  parseFilters,
  pickDefaultPeriod,
  repeatAbsences,
  resolveRange,
  rowsInRange,
  rowsOn,
  serializeFilters,
  summarizeOvertime,
  summarizeWorkHours,
  windowRange,
  bucketOf,
  type DashboardFilters,
  type DayBucket,
  type DayFlag,
} from "@/lib/attendance/dashboard";
import { businessToday } from "@/lib/attendance/format";
import { HR_CALENDAR_PERMISSIONS } from "@/lib/attendance/hr-calendar";
import { compareRates, groupOptions, weekdayShort } from "@/lib/attendance/insights";
import {
  toDistribution,
  toFrequentLate,
  toGroupStats,
  toKpiSet,
  toPunctuality,
  toRatePoints,
} from "@/lib/attendance/summary";
import { useAuth } from "@/lib/auth/auth-context";
import { cn } from "@/lib/utils";
import { usePermissions } from "@/lib/auth/use-permissions";

type DashboardView = "today" | "trends" | "muster" | "periods";
const VIEWS: DashboardView[] = ["today", "trends", "muster", "periods"];

const VIEW_LABELS: Record<DashboardView, string> = {
  today: "Today",
  trends: "Trends",
  muster: "Muster",
  periods: "Periods & reports",
};

function parseView(value: string | null): DashboardView {
  return (VIEWS as string[]).includes(value ?? "") ? (value as DashboardView) : "today";
}

/** Attendance command centre. The totals and charts come from `GET /v1/attendance/summary`, which
 * the backend counts over every attendance day in the window; the per-person lists and the muster
 * read `GET /v1/attendance/days` (plus the overtime / regularization / period endpoints). All of
 * them are DataScope-filtered server-side — the page adds display logic only, never access
 * control. Filters live in the URL so a view can be shared; the focus date is the end of the
 * selected range. */
function AttendanceDashboard() {
  const { user } = useAuth();
  const { can, canAny } = usePermissions();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const timezone = user?.company_timezone ?? "Asia/Kolkata";
  const today = businessToday(timezone);
  const canViewAll = can("ATTENDANCE.VIEW_ALL");
  const myEmployeeId = user?.employee_id ?? null;

  const [filters, setFilters] = useState<DashboardFilters>(() => parseFilters(searchParams ?? new URLSearchParams()));
  const [punchOpen, setPunchOpen] = useState(false);
  // Which part of the dashboard is on screen. "today" (the default) is omitted from the URL.
  const [view, setView] = useState<DashboardView>(() => parseView(searchParams?.get("view") ?? null));
  const scrollToListRef = useRef(false);

  const updateFilters = useCallback(
    (patch: Partial<DashboardFilters>) => {
      setFilters((prev) => ({ ...prev, ...patch }));
    },
    [],
  );
  const resetFilters = useCallback(() => setFilters(DEFAULT_FILTERS), []);

  // State is the source of truth; the URL mirrors it (shareable, survives reload).
  useEffect(() => {
    const params = serializeFilters(filters);
    if (view !== "today") params.set("view", view);
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [filters, view, pathname, router]);

  // A drill-down opens the employee list, which lives on the Today view: switch to it first, then
  // scroll once it has rendered.
  useEffect(() => {
    if (view === "today" && scrollToListRef.current) {
      scrollToListRef.current = false;
      document.getElementById("att-whos-in")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    }
  }, [view, filters]);

  const range = useMemo(() => resolveRange(filters, today), [filters, today]);
  const win = useMemo(() => windowRange(range), [range]);
  const focusIsToday = range.to === today;
  const focusLabel = focusIsToday ? "today" : formatShortDate(range.to);
  const rangeLabel =
    range.from === range.to ? formatShortDate(range.to) : `${formatShortDate(range.from)} – ${formatShortDate(range.to)}`;

  const data = useDashboardData({
    window: win,
    range: win,
    filters,
    legalEntityId: filters.legalEntityId,
    canListEmployees: can("EMPLOYEE.VIEW_ALL"),
    canListShifts: can("ORG.SHIFT.MANAGE"),
    canListEntities: can("ORG.LEGAL_ENTITY.MANAGE"),
    loadOperational: canViewAll || canAny(["ATTENDANCE.REGULARIZATION_APPROVE", "ATTENDANCE.OVERTIME_APPROVE"]),
  });

  const allDays = data.days.data;
  // Department / branch come from the employee directory (attendance days carry neither). Only the
  // people who actually appear in the days are looked up, in a few batched requests.
  const canListEmployees = can("EMPLOYEE.VIEW_ALL");
  const employeeIds = useMemo(() => Array.from(new Set((allDays ?? []).map((d) => d.employee_id))), [allDays]);
  const directory = useDirectoryDetails(employeeIds, canListEmployees);
  const directoryMap = directory.status === "ready" ? directory.data?.byEmployee : undefined;
  const directoryPending = canListEmployees && employeeIds.length > 0 && directory.status !== "ready" && directory.status !== "error";
  const mode: "org" | "team" | "self" | "pending" = canViewAll
    ? "org"
    : !allDays
      ? "pending"
      : allDays.some((d) => d.employee_id !== myEmployeeId)
        ? "team"
        : "self";

  // Every total and chart on the page: counted by the backend, only reshaped here.
  const summary = data.summary.data;
  const totals = useMemo(() => {
    if (!summary) return null;
    const ratePoints = toRatePoints(summary.daily);
    return {
      daily: summary.daily,
      kpi: toKpiSet(summary.focus),
      kpiCompare: summary.compare
        ? { kpi: toKpiSet(summary.compare), label: `last ${weekdayShort(summary.compare_date)}` }
        : null,
      distribution: toDistribution(summary.distribution),
      ratePoints,
      rateComparison: compareRates(ratePoints, summary.focus_date, summary.compare_date),
      // Punctuality and weekday patterns need more than one day to mean anything, so they cover
      // the whole trend window (never shorter than two weeks) rather than a single-day range.
      punctuality: toPunctuality(summary.punctuality),
      frequentLate: toFrequentLate(summary.frequent_late),
      weekdayStats: summary.weekday_absence,
      // The breakdown compares departments / branches with each other, so the backend ignores the
      // department and branch filters for it (otherwise picking one would leave nothing to compare).
      byDepartment: toGroupStats(summary.by_department),
      byBranch: toGroupStats(summary.by_branch),
    };
  }, [summary]);

  const employees = data.employees.data?.items;
  const employeesById = useMemo(() => indexEmployees(employees ?? []), [employees]);
  const shiftNames = useMemo(() => new Map((data.shifts.data ?? []).map((s) => [s.id, s.name])), [data.shifts.data]);
  const entityNames = useMemo(() => new Map((data.entities.data ?? []).map((e) => [e.id, e.name])), [data.entities.data]);
  const lookups = useMemo(
    () => ({
      employees: employees ?? [],
      shifts: (data.shifts.data ?? []).map((s) => ({ id: s.id, name: s.name })),
      entities: (data.entities.data ?? []).map((e) => ({ id: e.id, name: e.name })),
      employeeStatuses: Array.from(new Set((employees ?? []).map((e) => e.status).filter((s): s is string => !!s))).sort(),
      departments: groupOptions(directoryMap?.values() ?? [], "department", totals?.byDepartment),
      branches: groupOptions(directoryMap?.values() ?? [], "branch", totals?.byBranch),
    }),
    [employees, data.shifts.data, data.entities.data, directoryMap, totals],
  );

  const population = useMemo(
    () => applyPopulationFilters(allDays ?? [], filters, employeesById, directoryMap),
    [allDays, filters, employeesById, directoryMap],
  );
  const hasDirectoryFilter = Boolean(filters.department || filters.branch);
  const rangeRows = useMemo(() => rowsInRange(population, range), [population, range]);
  const focusRows = useMemo(() => rowsOn(population, range.to), [population, range.to]);
  const noRecord = useMemo(
    () =>
      focusIsToday && employees ? employeesWithoutRecord(focusRows, employees, filters, range.to, directoryMap) : [],
    [focusIsToday, employees, focusRows, filters, range.to, directoryMap],
  );

  // Needs Attention's whole-range items ("27 days · 22 employees") must drill into the same
  // `rangeRows` population that produced their count — not `focusRows` (the focus date only), or
  // the list silently represents a different, far smaller population than the number above it
  // (F5-1). `filters.scope` distinguishes that drill source from every focus-date drill (KPI
  // card, status chart, toolbar status select), which never set it and must keep drilling
  // `focusRows` exactly as before.
  const rangeScoped = filters.scope === "range" && (filters.bucket !== "" || filters.flag !== "");
  const listSource = rangeScoped ? rangeRows : focusRows;
  const listRows = useMemo<WhosInRow[]>(() => {
    const rows: WhosInRow[] = applyDrillFilters(listSource, filters).map((day) => ({
      id: day.id,
      employeeId: day.employee_id,
      day,
    }));
    // "No record yet" employees have no `attendance_date` and only ever apply to the focus date.
    const showNoRecord = !rangeScoped && !filters.bucket && (!filters.flag || filters.flag === "not_checked_in");
    if (showNoRecord) {
      for (const employee of noRecord) rows.push({ id: `no-record-${employee.id}`, employeeId: employee.id, day: null });
    }
    return rows;
  }, [listSource, rangeScoped, filters, noRecord]);

  // `data.overtime` is fetched over `win` (the widened trend-context window), not `range` (the
  // selected range) — needed so the trend figure below still has its ≥14-day context. Anything
  // that isn't the trend must apply the same employee/shift/employee-status population filter the
  // rest of the dashboard uses, then narrow to `range` — otherwise it silently includes up to 13
  // days of overtime from before the selected range (F6-1).
  const overtimeScoped = useMemo(() => {
    const records = data.overtime.data;
    if (!records) return null;
    const ids = new Set(population.map((d) => d.employee_id));
    return filters.employeeId || filters.shiftId || filters.employeeStatus ? records.filter((r) => ids.has(r.employee_id)) : records;
  }, [data.overtime.data, population, filters.employeeId, filters.shiftId, filters.employeeStatus]);
  const overtimeRangeRows = useMemo(
    () => (overtimeScoped ? overtimeScoped.filter((r) => r.attendance_date >= range.from && r.attendance_date <= range.to) : null),
    [overtimeScoped, range],
  );
  const overtimeSummary = useMemo(() => {
    if (!overtimeScoped || !overtimeRangeRows) return null;
    return { ...summarizeOvertime(overtimeRangeRows, range), trend: summarizeOvertime(overtimeScoped, win).trend };
  }, [overtimeScoped, overtimeRangeRows, range, win]);

  const blockedPeriods = useMemo(
    () => (data.periods.data ?? []).filter((p) => p.status === "OPEN" && p.last_validation_status === "BLOCKED"),
    [data.periods.data],
  );
  const attention = useMemo(
    () =>
      buildAttentionItems({
        rows: rangeRows,
        pendingRegularizations: data.regularizations.data,
        pendingOvertimeCount: overtimeSummary ? overtimeSummary.pendingCount : null,
        blockedPeriods: data.periods.status === "ready" ? blockedPeriods : null,
      }),
    [rangeRows, data.regularizations.data, overtimeSummary, data.periods.status, blockedPeriods],
  );
  const unavailableSources = [
    data.regularizations.status === "error" ? "pending regularizations" : null,
    data.overtime.status === "error" ? "pending overtime" : null,
    data.periods.status === "error" ? "payroll period status" : null,
  ].filter((s): s is string => s !== null);

  const workHours = useMemo(() => summarizeWorkHours(rangeRows), [rangeRows]);
  const hoursByDay = useMemo(() => dailyHours(population, win), [population, win]);
  const absentRangeDays = useMemo(() => rangeRows.filter((d) => bucketOf(d) === "ABSENT").length, [rangeRows]);
  const leaveRangeDays = useMemo(() => rangeRows.filter((d) => bucketOf(d) === "LEAVE").length, [rangeRows]);
  const repeat = useMemo(() => repeatAbsences(rangeRows), [rangeRows]);
  const muster = useMemo(
    () => buildMuster(population, musterDates(win), employeesById),
    [population, win, employeesById],
  );

  const winLabel = `${formatShortDate(win.from)} – ${formatShortDate(win.to)}`;
  const readinessPeriod = useMemo(
    () => pickDefaultPeriod((data.periods.data ?? []).filter((p) => p.status === "OPEN"), today),
    [data.periods.data, today],
  );
  const payrollBlockers = useMemo(
    () => attention.filter((item) => item.severity === "critical" || item.severity === "high"),
    [attention],
  );

  function drill(target: { bucket?: DayBucket; flag?: DayFlag; scope?: "range"; clear?: boolean }) {
    setFilters((prev) => {
      if (target.clear) return { ...prev, bucket: "", flag: "", scope: "" };
      const bucket = target.bucket ?? "";
      const flag = target.flag ?? "";
      // Omitting `scope` (every focus-date drill source) always resets it to "" — otherwise a
      // leftover range-scoped drill would silently carry over into an unrelated focus-date drill.
      const scope = target.scope ?? "";
      // Clicking the active drill again clears it.
      if (prev.bucket === bucket && prev.flag === flag && prev.scope === scope) return { ...prev, bucket: "", flag: "", scope: "" };
      return { ...prev, bucket, flag, scope };
    });
    scrollToListRef.current = true;
    setView("today");
  }

  const actions =
    mode !== "self" ? (
      <div className="flex flex-wrap items-center gap-2">
        {HR_CALENDAR_PERMISSIONS.every((code) => can(code)) ? (
          <Button asChild variant="outline">
            <Link href="/app/attendance/calendar">Calendar view</Link>
          </Button>
        ) : null}
        {can("ATTENDANCE.PUNCH") || can("ATTENDANCE.PUNCH_ON_BEHALF") ? (
          <Button type="button" onClick={() => setPunchOpen(true)}>
            Record punch
          </Button>
        ) : null}
      </div>
    ) : null;

  const header = (
    <PageHeader
      title="Attendance"
      description={
        mode === "self"
          ? "Your attendance, shift and requests."
          : "Who is working, who is absent, and what needs HR attention."
      }
      actions={actions}
    />
  );

  // --- first load / hard failure -------------------------------------------------------------
  if (mode === "self" && myEmployeeId) {
    return (
      <div className="space-y-6">
        {header}
        <SelfView employeeId={myEmployeeId} today={today} timezone={timezone} />
      </div>
    );
  }

  const listTitle = rangeScoped
    ? `Attendance, ${rangeLabel}`
    : focusIsToday
      ? "Today's attendance"
      : `Attendance on ${formatShortDate(range.to)}`;
  const drillDescription = [filters.bucket ? BUCKET_LABELS[filters.bucket] : null, filters.flag ? FLAG_LABELS[filters.flag] : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="space-y-6">
      {header}

      <AttendanceToolbar
        filters={filters}
        range={range}
        today={today}
        lookups={lookups}
        onChange={updateFilters}
        onReset={resetFilters}
      />

      {hasDirectoryFilter && !directoryMap && (directory.status === "error" || !canListEmployees) ? (
        <p role="note" className="text-xs text-foreground-muted">
          The department / branch filter applies to the totals but not to the employee lists: department data couldn&apos;t be loaded for your account.
        </p>
      ) : null}

      {(!allDays && data.days.status === "error") || (!totals && data.summary.status === "error") ? (
        <ErrorState
          message={
            data.days.error?.status === 403 || data.summary.error?.status === 403
              ? "You do not have permission to view attendance."
              : "Attendance couldn't be loaded. Please try again."
          }
          onRetry={
            data.days.error?.status === 403 || data.summary.error?.status === 403
              ? undefined
              : () => {
                  if (data.days.status === "error") data.days.retry();
                  if (data.summary.status === "error") data.summary.retry();
                }
          }
        />
      ) : !allDays || !totals || (hasDirectoryFilter && directoryPending) ? (
        <AttendanceDashboardSkeleton />
      ) : (
        <>
          {data.daysCoverage?.truncated ? (
            <p role="note" className="text-xs text-foreground-muted">
              {`Totals and charts count every attendance record, but the employee lists and heatmap show the most recent ${data.daysCoverage.loaded.toLocaleString()} of ${data.daysCoverage.total.toLocaleString()} in this range. Choose a shorter range to list them all.`}
            </p>
          ) : null}
          {data.employees.status === "error" || (data.employees.data?.truncated ?? false) ? (
            <p role="note" className="text-xs text-foreground-muted">
              {data.employees.data?.truncated
                ? `Employee names are loaded for the first ${data.employees.data.items.length} of ${data.employees.data.total} employees.`
                : "The employee directory couldn't be loaded — names fall back to IDs and “not checked in” excludes employees with no record yet."}
            </p>
          ) : null}

          <div role="tablist" aria-label="Attendance views" className="flex gap-1 overflow-x-auto border-b border-border">
            {VIEWS.map((key) => (
              <button
                key={key}
                id={`att-tab-${key}`}
                type="button"
                role="tab"
                aria-selected={view === key}
                aria-controls={`att-panel-${key}`}
                tabIndex={view === key ? 0 : -1}
                onClick={() => setView(key)}
                onKeyDown={(event) => {
                  const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
                  if (!step) return;
                  event.preventDefault();
                  const next = VIEWS[(VIEWS.indexOf(key) + step + VIEWS.length) % VIEWS.length];
                  setView(next);
                  document.getElementById(`att-tab-${next}`)?.focus();
                }}
                className={cn(
                  "relative whitespace-nowrap px-4 py-2.5 text-sm font-medium transition-[transform,colors] duration-motion-fast focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  // The underline grows out from the centre of the selected tab and shrinks away from the old one.
                  "after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:origin-center after:scale-x-0 after:rounded-full after:bg-primary after:transition-transform after:duration-motion-base active:scale-[0.97] motion-reduce:transform-none motion-reduce:after:transition-none",
                  view === key
                    ? "text-primary after:scale-x-100"
                    : "text-foreground-secondary hover:text-foreground",
                )}
              >
                {key === "periods" && mode !== "org" ? "Reports" : VIEW_LABELS[key]}
              </button>
            ))}
          </div>

          {view === "today" ? (
            <div role="tabpanel" id="att-panel-today" aria-labelledby="att-tab-today" className="animate-in fade-in-0 slide-in-from-bottom-1 space-y-6 duration-motion-base">
          <TodayPulse
            points={totals.ratePoints}
            focusDate={range.to}
            focusLabel={focusLabel}
            comparison={totals.rateComparison}
            distribution={totals.distribution}
            filters={filters}
            onDrill={(bucket) => drill({ bucket })}
          />

          <KpiGrid kpi={totals.kpi} filters={filters} focusLabel={focusLabel} compare={totals.kpiCompare} onDrill={drill} />

          <div className="grid items-start gap-6 lg:grid-cols-3">
            <SectionCard
              id="att-attention"
              title="Needs attention"
              description={`${rangeLabel} — what HR should act on.`}
              status="ready"
              className={mode === "org" && readinessPeriod ? "lg:col-span-2" : "lg:col-span-3"}
            >
              <NeedsAttention items={attention} unavailableSources={unavailableSources} rangeLabel={rangeLabel} onDrill={drill} />
            </SectionCard>
            {mode === "org" && readinessPeriod ? (
              <PayrollReadiness
                period={readinessPeriod}
                companyName={entityNames.get(readinessPeriod.legal_entity_id) ?? "Company"}
                today={today}
                blockers={payrollBlockers}
                rangeLabel={rangeLabel}
              />
            ) : null}
          </div>

          <SectionCard
            id="att-whos-in"
            title={listTitle}
            description={`${drillDescription ? `${drillDescription}. ` : ""}Snapshot from punches and the latest attendance calculation — not a live presence feed.`}
            status="ready"
            actions={
              filters.bucket || filters.flag ? (
                <Button type="button" size="sm" variant="outline" onClick={() => drill({ clear: true })}>
                  Clear drill-down
                </Button>
              ) : null
            }
          >
            <WhosInPanel
              rows={listRows}
              employeesById={employeesById}
              shiftNames={shiftNames}
              timezone={timezone}
              showDate={rangeScoped}
              directory={directoryMap}
            />
          </SectionCard>
            </div>
          ) : null}

          {view === "trends" ? (
            <div role="tabpanel" id="att-panel-trends" aria-labelledby="att-tab-trends" className="animate-in fade-in-0 slide-in-from-bottom-1 space-y-6 duration-motion-base">
          <SectionCard
            id="att-breakdown"
            title="Departments & branches"
            description="Who is in, and who is missing, in each part of the company. Click a row to filter the whole dashboard."
            status="ready"
          >
            <BreakdownPanel
              byDepartment={totals.byDepartment}
              byBranch={totals.byBranch}
              active={{ department: filters.department, branch: filters.branch }}
              onSelect={(key, value) => updateFilters({ [key]: filters[key] === value ? "" : value })}
              focusLabel={focusLabel}
            />
          </SectionCard>

          <div className="grid gap-6 lg:grid-cols-3">
            <SectionCard
              id="att-trend"
              title="Attendance trend"
              description="Rates are of employees expected to work."
              status="ready"
              className="lg:col-span-2"
            >
              <TrendChart days={totals.daily} range={win} />
            </SectionCard>
            <SectionCard
              id="att-status"
              title="Status distribution"
              description={`${focusIsToday ? "Today" : formatShortDate(range.to)} — click a status to list those employees.`}
              status="ready"
              empty={totals.distribution.every((d) => d.count === 0) ? { title: "No attendance records for this date.", icon: CalendarClock } : null}
            >
              <StatusChart distribution={totals.distribution} filters={filters} onDrill={(bucket) => drill({ bucket })} />
            </SectionCard>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <SectionCard
              id="att-punctuality"
              title="Punctuality"
              description={`${winLabel} — how punctual people are, and who is late again and again.`}
              status="ready"
            >
              <PunctualityPanel
                summary={totals.punctuality}
                frequent={totals.frequentLate}
                employeesById={employeesById}
                onViewLate={() => drill({ flag: "late", scope: "range" })}
              />
            </SectionCard>
            <SectionCard
              id="att-weekday"
              title="Absence by weekday"
              description={`${winLabel} — share of expected days missed, per weekday.`}
              status="ready"
            >
              <WeekdayPanel stats={totals.weekdayStats} />
            </SectionCard>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <SectionCard
              id="att-hours"
              title="Work hours"
              description={`${rangeLabel}. The chart spans at least the last 14 days for context.`}
              status="ready"
              empty={workHours.checkedInDays === 0 ? { title: "No hours recorded for this range.", description: "Nobody has a check-in in the selected range." } : null}
            >
              <WorkHoursPanel summary={workHours} daily={hoursByDay} />
            </SectionCard>
            <SectionCard
              id="att-overtime"
              title="Overtime"
              description={`${rangeLabel}, from overtime records.`}
              status={data.overtime.status}
              error={data.overtime.error}
              onRetry={data.overtime.retry}
              unavailable={data.overtime.status === "idle" ? "Overtime records aren't available for your role." : null}
              empty={overtimeSummary && overtimeSummary.totalDetectedMinutes === 0 ? { title: "No overtime recorded for this period." } : null}
            >
              {overtimeSummary ? <OvertimePanel summary={overtimeSummary} /> : null}
            </SectionCard>
            <SectionCard
              id="att-absence"
              title="Leave & absence"
              description="Operational view — Leave stays the system of record."
              status="ready"
            >
              <AbsenceInsights
                kpi={totals.kpi}
                focusLabel={focusLabel}
                rangeAbsentDays={absentRangeDays}
                rangeLeaveDays={leaveRangeDays}
                repeat={repeat}
                employeesById={employeesById}
                onDrillEmployee={(id) => updateFilters({ employeeId: id })}
              />
            </SectionCard>
          </div>
            </div>
          ) : null}

          {view === "muster" ? (
            <div role="tabpanel" id="att-panel-muster" aria-labelledby="att-tab-muster" className="animate-in fade-in-0 slide-in-from-bottom-1 space-y-6 duration-motion-base">
          <SectionCard
            id="att-muster"
            title="Attendance heatmap"
            description="Employee × day status grid (muster)."
            status="ready"
            empty={muster.rows.length === 0 ? { title: "No attendance days to show.", icon: CalendarClock } : null}
          >
            <MusterHeatmap muster={muster} />
          </SectionCard>
            </div>
          ) : null}

          {view === "periods" ? (
            <div role="tabpanel" id="att-panel-periods" aria-labelledby="att-tab-periods" className="animate-in fade-in-0 slide-in-from-bottom-1 space-y-6 duration-motion-base">
          {mode === "org" ? (
            <div className="grid gap-6 lg:grid-cols-2">
              <PeriodStatus
                periods={data.periods}
                entityNames={entityNames}
                today={today}
                entities={lookups.entities}
                legalEntityId={filters.legalEntityId}
                onEntityChange={(legalEntityId) => updateFilters({ legalEntityId })}
              />
              <MonthlySummary periods={data.periods} today={today} />
            </div>
          ) : null}

          <ReportsPanel
            rows={rangeRows}
            employeesById={employeesById}
            overtime={{ ...data.overtime, data: overtimeRangeRows }}
            periods={data.periods}
            timezone={timezone}
            today={today}
            rangeLabel={rangeLabel}
          />
            </div>
          ) : null}
        </>
      )}

      <PunchEntryDialog open={punchOpen} onOpenChange={setPunchOpen} onRecorded={() => data.days.retry()} />
    </div>
  );
}

export default function AttendanceDashboardPage() {
  return (
    <Suspense fallback={<AttendanceDashboardSkeleton />}>
      <AttendanceDashboard />
    </Suspense>
  );
}
