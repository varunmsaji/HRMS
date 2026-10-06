"use client";

import { CalendarClock } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { AbsenceInsights } from "@/components/attendance/dashboard/absence-insights";
import { CoverageNotice } from "@/components/attendance/dashboard/coverage-notice";
import { KpiGrid } from "@/components/attendance/dashboard/kpi-grid";
import { MusterHeatmap } from "@/components/attendance/dashboard/muster-heatmap";
import { NeedsAttention } from "@/components/attendance/dashboard/needs-attention";
import { OvertimePanel } from "@/components/attendance/dashboard/overtime-panel";
import { MonthlySummary, PeriodStatus } from "@/components/attendance/dashboard/period-status";
import { ReportsPanel } from "@/components/attendance/dashboard/reports-panel";
import { SectionCard } from "@/components/attendance/dashboard/section-card";
import { SelfView } from "@/components/attendance/dashboard/self-view";
import { StatusChart } from "@/components/attendance/dashboard/status-chart";
import { AttendanceToolbar } from "@/components/attendance/dashboard/toolbar";
import { TrendChart } from "@/components/attendance/dashboard/trend-chart";
import { useDashboardData } from "@/components/attendance/dashboard/use-dashboard-data";
import { WhosInPanel, type WhosInRow } from "@/components/attendance/dashboard/whos-in-panel";
import { WorkHoursPanel } from "@/components/attendance/dashboard/work-hours-panel";
import { PunchEntryDialog } from "@/components/attendance/punch-entry-dialog";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
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
  computeKpis,
  dailyHours,
  employeesWithoutRecord,
  formatShortDate,
  indexEmployees,
  musterDates,
  parseFilters,
  repeatAbsences,
  resolveRange,
  rowsInRange,
  rowsOn,
  serializeFilters,
  statusDistribution,
  summarizeOvertime,
  summarizeWorkHours,
  windowRange,
  bucketOf,
  type DashboardFilters,
  type DayBucket,
  type DayFlag,
} from "@/lib/attendance/dashboard";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";

/** Attendance command centre. Every number comes from `GET /v1/attendance/days` (and the
 * overtime / regularization / period endpoints), which are DataScope-filtered server-side — the
 * page adds display logic only, never access control. Filters live in the URL so a view can be
 * shared; the focus date is the end of the selected range. */
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

  const updateFilters = useCallback(
    (patch: Partial<DashboardFilters>) => {
      setFilters((prev) => ({ ...prev, ...patch }));
    },
    [],
  );
  const resetFilters = useCallback(() => setFilters(DEFAULT_FILTERS), []);

  // State is the source of truth; the URL mirrors it (shareable, survives reload).
  useEffect(() => {
    const qs = serializeFilters(filters).toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [filters, pathname, router]);

  const range = useMemo(() => resolveRange(filters, today), [filters, today]);
  const win = useMemo(() => windowRange(range), [range]);
  const focusIsToday = range.to === today;
  const focusLabel = focusIsToday ? "today" : formatShortDate(range.to);
  const rangeLabel =
    range.from === range.to ? formatShortDate(range.to) : `${formatShortDate(range.from)} – ${formatShortDate(range.to)}`;

  const data = useDashboardData({
    window: win,
    range: win,
    legalEntityId: filters.legalEntityId,
    canListEmployees: can("EMPLOYEE.VIEW_ALL"),
    canListShifts: can("ORG.SHIFT.MANAGE"),
    canListEntities: can("ORG.LEGAL_ENTITY.MANAGE"),
    loadOperational: canViewAll || canAny(["ATTENDANCE.REGULARIZATION_APPROVE", "ATTENDANCE.OVERTIME_APPROVE"]),
  });

  const allDays = data.days.data;
  const mode: "org" | "team" | "self" | "pending" = canViewAll
    ? "org"
    : !allDays
      ? "pending"
      : allDays.some((d) => d.employee_id !== myEmployeeId)
        ? "team"
        : "self";

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
    }),
    [employees, data.shifts.data, data.entities.data],
  );

  const population = useMemo(
    () => applyPopulationFilters(allDays ?? [], filters, employeesById),
    [allDays, filters, employeesById],
  );
  const rangeRows = useMemo(() => rowsInRange(population, range), [population, range]);
  const focusRows = useMemo(() => rowsOn(population, range.to), [population, range.to]);
  const noRecord = useMemo(
    () =>
      focusIsToday && employees ? employeesWithoutRecord(focusRows, employees, filters, range.to) : [],
    [focusIsToday, employees, focusRows, filters, range.to],
  );
  const kpi = useMemo(() => computeKpis(focusRows, noRecord.length), [focusRows, noRecord.length]);
  const distribution = useMemo(() => statusDistribution(focusRows), [focusRows]);

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
    if (typeof document !== "undefined") {
      document.getElementById("att-whos-in")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    }
  }

  const actions =
    mode !== "self" && (can("ATTENDANCE.PUNCH") || can("ATTENDANCE.PUNCH_ON_BEHALF")) ? (
      <Button type="button" onClick={() => setPunchOpen(true)}>
        Record punch
      </Button>
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
        showEntity={canViewAll}
        onChange={updateFilters}
        onReset={resetFilters}
      />

      {!allDays && data.days.status === "error" ? (
        <ErrorState
          message={
            data.days.error?.status === 403
              ? "You do not have permission to view attendance."
              : "Attendance couldn't be loaded. Please try again."
          }
          onRetry={data.days.error?.status === 403 ? undefined : data.days.retry}
        />
      ) : !allDays ? (
        <LoadingState label="Loading attendance…" />
      ) : (
        <>
          {data.employees.status === "error" || (data.employees.data?.truncated ?? false) ? (
            <p role="note" className="text-xs text-foreground-muted">
              {data.employees.data?.truncated
                ? `Employee names are loaded for the first ${data.employees.data.items.length} of ${data.employees.data.total} employees.`
                : "The employee directory couldn't be loaded — names fall back to IDs and “not checked in” excludes employees with no record yet."}
            </p>
          ) : null}

          <KpiGrid kpi={kpi} filters={filters} focusLabel={focusLabel} onDrill={drill} />

          <div className="grid gap-6 lg:grid-cols-3">
            <SectionCard
              id="att-attention"
              title="Needs attention"
              description={`${rangeLabel} — what HR should act on.`}
              status="ready"
              className="lg:col-span-2"
            >
              <NeedsAttention items={attention} unavailableSources={unavailableSources} rangeLabel={rangeLabel} onDrill={drill} />
            </SectionCard>
            <SectionCard
              id="att-status"
              title="Status distribution"
              description={`${focusIsToday ? "Today" : formatShortDate(range.to)} — click a status to list those employees.`}
              status="ready"
              empty={focusRows.length === 0 ? { title: "No attendance records for this date.", icon: CalendarClock } : null}
            >
              <StatusChart distribution={distribution} filters={filters} onDrill={(bucket) => drill({ bucket })} />
            </SectionCard>
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
              <TrendChart rows={population} range={win} />
            </SectionCard>
            <SectionCard
              id="att-absence"
              title="Leave & absence"
              description="Operational view — Leave stays the system of record."
              status="ready"
            >
              <AbsenceInsights
                kpi={kpi}
                focusLabel={focusLabel}
                rangeAbsentDays={absentRangeDays}
                rangeLeaveDays={leaveRangeDays}
                repeat={repeat}
                employeesById={employeesById}
                onDrillEmployee={(id) => updateFilters({ employeeId: id })}
              />
            </SectionCard>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
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
          </div>

          <SectionCard
            id="att-breakdowns"
            title="Department, location & work-mode breakdowns"
            status="ready"
            unavailable="Not available yet: attendance days carry no department, branch, designation or work-mode, so these breakdowns can't be built without one request per employee. See “Not shown on this dashboard” below."
          />

          <SectionCard
            id="att-muster"
            title="Attendance heatmap"
            description="Employee × day status grid (muster)."
            status="ready"
            empty={muster.rows.length === 0 ? { title: "No attendance days to show.", icon: CalendarClock } : null}
          >
            <MusterHeatmap muster={muster} />
          </SectionCard>

          {mode === "org" ? (
            <div className="grid gap-6 lg:grid-cols-2">
              <PeriodStatus periods={data.periods} entityNames={entityNames} today={today} />
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

          <CoverageNotice />
        </>
      )}

      <PunchEntryDialog open={punchOpen} onOpenChange={setPunchOpen} onRecorded={() => data.days.retry()} />
    </div>
  );
}

export default function AttendanceDashboardPage() {
  return (
    <Suspense fallback={<LoadingState label="Loading attendance…" />}>
      <AttendanceDashboard />
    </Suspense>
  );
}
