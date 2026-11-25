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
import { useSection } from "@/components/attendance/dashboard/use-dashboard-data";
import { useTeamSize } from "@/components/attendance/dashboard/use-team-size";
import { PatternAlertsPanel } from "@/components/attendance/dashboard/pattern-alerts";
import { MusterHeatmap } from "@/components/attendance/dashboard/muster-heatmap";
import { NeedsAttention } from "@/components/attendance/dashboard/needs-attention";
import { NotCalculatedNotice } from "@/components/attendance/dashboard/not-calculated-notice";
import { OvertimePanel } from "@/components/attendance/dashboard/overtime-panel";
import { PayrollReadiness, payrollNeedsAttention } from "@/components/attendance/dashboard/payroll-readiness";
import { ReportsPanel } from "@/components/attendance/dashboard/reports-panel";
import { SectionCard } from "@/components/attendance/dashboard/section-card";
import { SelfView } from "@/components/attendance/dashboard/self-view";
import { AttendanceToolbar } from "@/components/attendance/dashboard/toolbar";
import { TodayPulse } from "@/components/attendance/dashboard/today-pulse";
import { TrendChart } from "@/components/attendance/dashboard/trend-chart";
import { useDashboardData, useDirectoryDetails } from "@/components/attendance/dashboard/use-dashboard-data";
import { WhosInPanel, type RowFix, type RowMismatch, type WhosInRow } from "@/components/attendance/dashboard/whos-in-panel";
import { WorkHoursPanel } from "@/components/attendance/dashboard/work-hours-panel";
import { KeepLeaveDialog } from "@/components/attendance/keep-leave-dialog";
import { MarkDayDialog, type MarkDayEmployee } from "@/components/attendance/mark-day-dialog";
import { PunchEntryDialog } from "@/components/attendance/punch-entry-dialog";
import { ErrorState } from "@/components/common/error-state";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import {
  BUCKET_LABELS,
  DEFAULT_FILTERS,
  LATE_BANDS,
  type DateRange,
  type DrillScope,
  type LateBandKey,
  type WeekdayKey,
  FLAG_LABELS,
  applyDrillFilters,
  applyPopulationFilters,
  buildAttentionItems,
  buildMuster,
  dailyHours,
  employeeName,
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
  weekdayLabel,
  windowRange,
  bucketOf,
  type DashboardFilters,
  type DayBucket,
  type DayFlag,
} from "@/lib/attendance/dashboard";
import {
  businessToday,
  formatClockTime,
  formatDateTime,
  isoToDatetimeLocal,
  nowInZoneForDatetimeLocal,
} from "@/lib/attendance/format";
import { mismatchOf } from "@/lib/attendance/mismatch";
import type { AttendanceDay } from "@/lib/attendance/types";
import { HR_CALENDAR_PERMISSIONS } from "@/lib/attendance/hr-calendar";
import { compareRates, groupOptions, weekdayShort } from "@/lib/attendance/insights";
import {
  toDistribution,
  toFrequentLate,
  toGroupStats,
  toKpiSet,
  toPunctuality,
  summaryQuery,
  toRatePoints,
} from "@/lib/attendance/summary";
import type { PatternAlerts } from "@/lib/attendance/patterns";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { cn } from "@/lib/utils";
import { usePermissions } from "@/lib/auth/use-permissions";

type DashboardView = "today" | "trends" | "reports";
const VIEWS: DashboardView[] = ["today", "trends", "reports"];

const VIEW_LABELS: Record<DashboardView, string> = {
  today: "Today",
  trends: "Trends",
  reports: "Reports",
};

/** The list on the Today view can also be read as the employee × day grid (the old Muster tab). */
type ListLayout = "list" | "grid";

/** Links from before the tabs were merged keep working: `periods` was the Reports tab, and
 * `muster` is now the grid layout of the Today list. */
function parseView(value: string | null): DashboardView {
  if (value === "periods") return "reports";
  return (VIEWS as string[]).includes(value ?? "") ? (value as DashboardView) : "today";
}

function parseLayout(params: URLSearchParams | null): ListLayout {
  return params?.get("layout") === "grid" || params?.get("view") === "muster" ? "grid" : "list";
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
  // `null` = closed. Kept as one state object so the dialog gets a stable employee list.
  const [markDay, setMarkDay] = useState<{ employees: MarkDayEmployee[]; date?: string } | null>(null);
  const canMarkDay = can("ATTENDANCE.PUNCH_ON_BEHALF");
  // Fixing a mismatched row opens one of these in place, so HR does not have to leave the list.
  const [punchFix, setPunchFix] = useState<{ employeeId: string; label: string; direction: "IN" | "OUT"; time: string } | null>(null);
  const [keepLeaveDay, setKeepLeaveDay] = useState<AttendanceDay | null>(null);
  // Which part of the dashboard is on screen. "today" (the default) is omitted from the URL.
  const [view, setView] = useState<DashboardView>(() => parseView(searchParams?.get("view") ?? null));
  const [layout, setLayout] = useState<ListLayout>(() => parseLayout(searchParams));
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
    if (view === "today" && layout === "grid") params.set("layout", "grid");
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [filters, view, layout, pathname, router]);

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
  // A manager is someone with direct reports, known before any attendance rows arrive; reading the
  // rows is the fallback when that lookup fails or the caller has an employee record but no reports.
  const teamSize = useTeamSize(myEmployeeId, !canViewAll && can("EMPLOYEE.VIEW"));
  const mode: "org" | "team" | "self" | "pending" = canViewAll
    ? "org"
    : teamSize.status === "loading"
      ? "pending"
      : teamSize.status === "ready" && teamSize.total > 0
        ? "team"
        : !allDays
          ? "pending"
          : allDays.some((d) => d.employee_id !== myEmployeeId)
            ? "team"
            : "self";

  // Every total and chart on the page: counted by the backend, only reshaped here.
  const summary = data.summary.data;
  // When the focus day's rows were last calculated (not when this page fetched them).
  const calculatedAt = summary?.calculated_at ?? null;
  const totals = useMemo(() => {
    if (!summary) return null;
    const ratePoints = toRatePoints(summary.daily);
    const kpi = toKpiSet(summary.focus);
    // No row for anyone on the focus day: nothing has been calculated, so there is nothing fair
    // to compare with last week's full day.
    const awaitingRecords = kpi.totalEmployees > 0 && kpi.noRecord >= kpi.totalEmployees;
    return {
      daily: summary.daily,
      kpi,
      awaitingRecords,
      kpiCompare: summary.compare && !awaitingRecords
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
  // Listed for any focus date, not only today: on a past date an employed person with no row is a
  // day that was never calculated, and HR needs to see it rather than have them silently missing.
  const noRecord = useMemo(
    () => (employees ? employeesWithoutRecord(focusRows, employees, filters, range.to, directoryMap) : []),
    [employees, focusRows, filters, range.to, directoryMap],
  );

  // Needs Attention's whole-range items ("27 days · 22 employees") must drill into the same
  // `rangeRows` population that produced their count — not `focusRows` (the focus date only), or
  // the list silently represents a different, far smaller population than the number above it
  // (F5-1). `filters.scope` distinguishes that drill source from every focus-date drill (KPI
  // card, status chart, toolbar status select), which never set it and must keep drilling
  // `focusRows` exactly as before.
  const rangeScoped = filters.scope !== "" && (filters.bucket !== "" || filters.flag !== "");
  // A chart that counts the fetched window (range widened for context) drills into that window.
  const windowRows = useMemo(() => rowsInRange(population, win), [population, win]);
  const listSource = !rangeScoped ? focusRows : filters.scope === "window" ? windowRows : rangeRows;
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

  // Who keeps being late or absent, looked at up to the end of the selected range, with the
  // dashboard's own population filters. The server limits it to the people the caller may see.
  const patternQuery = useMemo(() => {
    const query = summaryQuery(range, filters);
    delete query.date_from;
    delete query.date_to;
    return new URLSearchParams({ as_of: range.to, ...query }).toString();
  }, [range, filters]);
  const patterns = useSection<PatternAlerts>(
    () => apiClient.get<PatternAlerts>(`/attendance/pattern-alerts?${patternQuery}`),
    `patterns|${patternQuery}`,
    mode === "org" || mode === "team",
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

  // After any fix the totals and the list must both reload, or the KPI tiles keep showing the
  // problem that was just settled.
  const retryDays = data.days.retry;
  const retrySummary = data.summary.retry;
  const refreshAll = useCallback(() => {
    retryDays();
    retrySummary();
  }, [retryDays, retrySummary]);

  // A correction request the employee already raised settles the day better than an HR punch, so
  // it comes first when there is one.
  const pendingRequestByDay = useMemo(
    () => new Map((data.regularizations.data ?? []).map((r) => [`${r.employee_id}|${r.attendance_date}`, r])),
    [data.regularizations.data],
  );
  const canApproveRegularization = can("ATTENDANCE.REGULARIZATION_APPROVE");
  const canRecompute = can("ATTENDANCE.RECOMPUTE");
  const mismatchFor = useCallback(
    (row: WhosInRow): RowMismatch | null => {
      const day = row.day;
      if (!day) return null;
      const mismatch = mismatchOf(day);
      if (!mismatch) return null;
      const label = employeeName(employeesById.get(row.employeeId), row.employeeId);
      const when = formatShortDate(day.attendance_date);
      const fixes: RowFix[] = [];
      const request = pendingRequestByDay.get(`${day.employee_id}|${day.attendance_date}`);
      if (request) {
        const verb = canApproveRegularization ? "Review correction request" : "View correction request";
        fixes.push({ key: "request", label: verb, ariaLabel: `${verb} from ${label} for ${when}`, href: `/app/regularizations/${request.id}`, primary: true });
      } else if (mismatch.kind === "work_on_leave") {
        if (canRecompute) {
          fixes.push({ key: "keep-leave", label: "Keep leave", ariaLabel: `Keep leave for ${label} on ${when}`, onClick: () => setKeepLeaveDay(day), primary: true });
        }
        fixes.push({ key: "cancel-leave", label: "Cancel leave", ariaLabel: `Cancel ${label}'s leave on ${when} in Leave`, href: "/app/leave-applications" });
      } else if (mismatch.kind === "no_punches" && canMarkDay) {
        fixes.push({
          key: "mark-present",
          label: "Mark present",
          ariaLabel: `Mark ${label} present on ${when}`,
          onClick: () => setMarkDay({ employees: [{ id: day.employee_id, label }], date: day.attendance_date }),
          primary: true,
        });
      } else if ((mismatch.kind === "missing_out" || mismatch.kind === "missing_in") && canMarkDay) {
        // Only when exactly one side is missing. An "incomplete" day with both punches can be
        // incomplete for another reason (an unresolved break), so a prefilled punch could record
        // an unrelated extra one: that case offers Open day only.
        const direction: "IN" | "OUT" = day.actual_first_in ? "OUT" : "IN";
        // Start from the shift's own start or end, but never a moment that has not happened yet.
        const scheduled = direction === "IN" ? day.scheduled_start : day.scheduled_end;
        const now = nowInZoneForDatetimeLocal(timezone);
        let time = scheduled ? isoToDatetimeLocal(scheduled, timezone) : `${day.attendance_date}T${direction === "IN" ? "09:00" : "18:00"}`;
        if (time > now) time = now;
        const verb = direction === "IN" ? "Add punch-in" : "Add punch-out";
        fixes.push({
          key: "punch",
          label: verb,
          ariaLabel: `${verb} for ${label} on ${when}`,
          onClick: () => setPunchFix({ employeeId: day.employee_id, label, direction, time }),
          primary: true,
        });
      }
      fixes.push({ key: "open", label: "Open day", ariaLabel: `Open ${label}'s attendance for ${when}`, href: `/app/attendance/${day.id}`, primary: fixes.length === 0 });
      return { reason: mismatch.reason, fixes };
    },
    [employeesById, pendingRequestByDay, canApproveRegularization, canRecompute, canMarkDay, timezone],
  );

  function drill(target: {
    bucket?: DayBucket;
    flag?: DayFlag;
    scope?: DrillScope;
    lateBand?: LateBandKey;
    weekday?: WeekdayKey;
    clear?: boolean;
  }) {
    const none: Pick<DashboardFilters, "bucket" | "flag" | "scope" | "lateBand" | "weekday"> = {
      bucket: "",
      flag: "",
      scope: "",
      lateBand: "",
      weekday: "",
    };
    setFilters((prev) => {
      if (target.clear) return { ...prev, ...none };
      const next: Pick<DashboardFilters, "bucket" | "flag" | "scope" | "lateBand" | "weekday"> = {
        bucket: target.bucket ?? "",
        flag: target.flag ?? "",
        // Omitting `scope` (every focus-date drill source) always resets it to "" — otherwise a
        // leftover range-scoped drill would silently carry over into an unrelated focus-date drill.
        scope: target.scope ?? "",
        lateBand: target.lateBand ?? "",
        weekday: target.weekday ?? "",
      };
      // Clicking the active drill again clears it.
      if (
        prev.bucket === next.bucket &&
        prev.flag === next.flag &&
        prev.scope === next.scope &&
        prev.lateBand === next.lateBand &&
        prev.weekday === next.weekday
      ) {
        return { ...prev, ...none };
      }
      return { ...prev, ...next };
    });
    scrollToListRef.current = true;
    setView("today");
    setLayout("list");
  }

  /** Opens the days behind a trend point: that period becomes the range, with no drill left over. */
  function focusPeriod(period: DateRange) {
    setFilters((prev) => ({ ...prev, preset: "custom", from: period.from, to: period.to, bucket: "", flag: "", scope: "", lateBand: "", weekday: "" }));
    scrollToListRef.current = true;
    setView("today");
    setLayout("list");
  }

  const actions =
    mode !== "self" ? (
      <div className="flex flex-wrap items-center gap-2">
        {HR_CALENDAR_PERMISSIONS.every((code) => can(code)) ? (
          <Button asChild variant="outline">
            <Link href="/app/attendance/calendar">Calendar view</Link>
          </Button>
        ) : null}
        {can("ATTENDANCE.PUNCH") || canMarkDay ? (
          <Button type="button" variant={canMarkDay ? "outline" : "default"} onClick={() => setPunchOpen(true)}>
            Record punch
          </Button>
        ) : null}
        {canMarkDay ? (
          <Button type="button" onClick={() => setMarkDay({ employees: [] })}>
            Mark attendance
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
          : mode === "team"
            ? "Your team: who is working, who is absent, and what needs your approval."
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
  const drillDescription = [
    filters.bucket ? BUCKET_LABELS[filters.bucket] : null,
    filters.weekday ? `on ${weekdayLabel(filters.weekday)}` : null,
    filters.flag ? FLAG_LABELS[filters.flag] : null,
    filters.lateBand ? LATE_BANDS[filters.lateBand].label : null,
    filters.scope === "window" ? winLabel : null,
  ]
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

          {mode === "team" ? (
            <p className="text-sm text-foreground-secondary" data-testid="team-scope">
              {teamSize.status === "ready" && teamSize.total > 0
                ? `Showing your team: ${teamSize.total} ${teamSize.total === 1 ? "person reports" : "people report"} to you. Company totals and payroll close are with HR.`
                : "Showing the people you can see. Company totals and payroll close are with HR."}
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
                {VIEW_LABELS[key]}
              </button>
            ))}
          </div>

          {view === "today" ? (
            <div role="tabpanel" id="att-panel-today" aria-labelledby="att-tab-today" className="animate-in fade-in-0 slide-in-from-bottom-1 space-y-6 duration-motion-base">
          {!focusIsToday ? (
            <NotCalculatedNotice
              date={range.to}
              dateLabel={focusLabel}
              employeeIds={noRecord.map((employee) => employee.id)}
              canRecalculate={canRecompute}
            />
          ) : null}
          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,4fr)_minmax(0,8fr)]">
            <TodayPulse
              points={totals.ratePoints}
              focusDate={range.to}
              focusLabel={focusLabel}
              comparison={totals.rateComparison}
              awaitingRecords={totals.awaitingRecords}
            />
            <KpiGrid kpi={totals.kpi} filters={filters} focusLabel={focusLabel} compare={totals.kpiCompare} onDrill={drill} />
          </div>

          <SectionCard
            id="att-attention"
            title="Needs attention"
            description={`Attendance items cover ${rangeLabel}. Pending requests are counted whatever their date.`}
            status="ready"
          >
            <NeedsAttention items={attention} unavailableSources={unavailableSources} rangeLabel={rangeLabel} onDrill={drill} />
          </SectionCard>

          {mode === "org" && readinessPeriod && payrollNeedsAttention(readinessPeriod, today, payrollBlockers) ? (
            <PayrollReadiness
              compact
              period={readinessPeriod}
              companyName={entityNames.get(readinessPeriod.legal_entity_id) ?? "Company"}
              today={today}
              blockers={payrollBlockers}
              rangeLabel={rangeLabel}
            />
          ) : null}

          <SectionCard
            id={layout === "grid" ? "att-muster" : "att-whos-in"}
            title={layout === "grid" ? "Attendance grid" : listTitle}
            description={
              layout === "grid"
                ? `Each employee's status, day by day, ${winLabel}. Follows the filters above.`
                : `${drillDescription ? `${drillDescription}. ` : ""}Snapshot from punches and the latest attendance calculation — not a live presence feed.${
                    calculatedAt
                      ? ` Last calculated ${focusIsToday ? `at ${formatClockTime(calculatedAt, timezone)}` : formatDateTime(calculatedAt, timezone)}.`
                      : ""
                  }${data.summary.loadedAt ? ` Loaded at ${formatClockTime(new Date(data.summary.loadedAt).toISOString(), timezone)}.` : ""}`
            }
            status="ready"
            empty={layout === "grid" && muster.rows.length === 0 ? { title: "No attendance days to show.", icon: CalendarClock } : null}
            actions={
              <>
                {layout === "list" && (filters.bucket || filters.flag) ? (
                  <Button type="button" size="sm" variant="outline" onClick={() => drill({ clear: true })}>
                    Clear drill-down
                  </Button>
                ) : null}
                <div role="group" aria-label="Show as" className="inline-flex rounded-md border border-border p-0.5">
                  {(["list", "grid"] as const).map((option) => (
                    <button
                      key={option}
                      type="button"
                      aria-pressed={layout === option}
                      onClick={() => setLayout(option)}
                      className={cn(
                        "rounded px-2.5 py-1 text-xs font-medium capitalize transition-colors",
                        layout === option ? "bg-primary text-on-primary" : "text-foreground-secondary hover:bg-muted",
                      )}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </>
            }
          >
            {layout === "grid" ? (
              <MusterHeatmap muster={muster} exportQuery={summaryQuery(range, filters)} />
            ) : (
              <WhosInPanel
                rows={listRows}
                employeesById={employeesById}
                shiftNames={shiftNames}
                timezone={timezone}
                showDate={rangeScoped}
                directory={directoryMap}
                fallbackDate={range.to}
                onMarkMany={canMarkDay ? ({ employees, date }) => setMarkDay({ employees, date }) : undefined}
                mismatchFor={mismatchFor}
              />
            )}
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

          <SectionCard
            id="att-trend"
            title="Attendance trend"
            description="Rates are of employees expected to work."
            status="ready"
          >
            <TrendChart days={totals.daily} range={win} onSelectPeriod={focusPeriod} />
          </SectionCard>

          <SectionCard
            id="att-patterns"
            title="Patterns to look at"
            description={
              patterns.data
                ? `People who keep being late or absent: ${patterns.data.thresholds.late_days}+ late days, ${patterns.data.thresholds.absent_days}+ absent days or ${patterns.data.thresholds.incomplete_days}+ missing punches in ${patterns.data.thresholds.window_days} days, or the same weekday ${patterns.data.thresholds.weekday_absences}+ times in ${patterns.data.thresholds.weekday_window_days} days. A prompt to look, not a finding.`
                : "People who keep being late or absent."
            }
            status={patterns.status}
            error={patterns.error}
            onRetry={patterns.retry}
            unavailable={patterns.status === "idle" ? "Pattern alerts aren't available for your role." : null}
            empty={patterns.data && patterns.data.alerts.length === 0 ? { title: "No patterns found.", description: "Nobody has crossed a threshold." } : null}
          >
            {patterns.data ? <PatternAlertsPanel data={patterns.data} employeesById={employeesById} /> : null}
          </SectionCard>

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
                onViewBand={(key) => drill({ flag: "late", scope: "window", lateBand: key })}
              />
            </SectionCard>
            <SectionCard
              id="att-absence"
              title="Absence & leave"
              description={`${rangeLabel} — operational view; Leave stays the system of record.`}
              status="ready"
            >
              <div className="space-y-5">
                <AbsenceInsights
                  rangeAbsentDays={absentRangeDays}
                  rangeLeaveDays={leaveRangeDays}
                  repeat={repeat}
                  employeesById={employeesById}
                  onDrillEmployee={(id) => updateFilters({ employeeId: id })}
                />
                <div>
                  <h3 className="mb-2 text-sm font-medium text-foreground">By weekday</h3>
                  <p className="mb-2 text-xs text-foreground-muted">{winLabel} — share of expected days missed.</p>
                  <WeekdayPanel
                    stats={totals.weekdayStats}
                    onSelectWeekday={(index) => drill({ bucket: "ABSENT", scope: "window", weekday: String(index) as WeekdayKey })}
                  />
                </div>
              </div>
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
            </div>
          ) : null}

          {view === "reports" ? (
            <div role="tabpanel" id="att-panel-reports" aria-labelledby="att-tab-reports" className="animate-in fade-in-0 slide-in-from-bottom-1 space-y-6 duration-motion-base">
          {mode === "org" ? (
            <p className="text-sm text-foreground-secondary">
              Closing the month? Periods and the monthly summary are in{" "}
              <Link href="/app/attendance-periods" className="font-medium text-primary hover:underline">
                Payroll → Attendance periods
              </Link>
              .
            </p>
          ) : null}

          <ReportsPanel
            rows={rangeRows}
            employeesById={employeesById}
            overtime={{ ...data.overtime, data: overtimeRangeRows }}
            periods={data.periods}
            timezone={timezone}
            today={today}
            rangeLabel={rangeLabel}
            exportQuery={summaryQuery(range, filters)}
            showPayroll={mode === "org"}
          />
            </div>
          ) : null}
        </>
      )}

      <PunchEntryDialog open={punchOpen} onOpenChange={setPunchOpen} onRecorded={refreshAll} />
      <PunchEntryDialog
        open={punchFix !== null}
        onOpenChange={(next) => (next ? null : setPunchFix(null))}
        employeeId={punchFix?.employeeId}
        employeeLabel={punchFix?.label}
        initialDirection={punchFix?.direction}
        initialTime={punchFix?.time}
        onRecorded={refreshAll}
      />
      {keepLeaveDay ? (
        <KeepLeaveDialog
          open
          onOpenChange={(next) => (next ? null : setKeepLeaveDay(null))}
          day={keepLeaveDay}
          onDone={() => {
            setKeepLeaveDay(null);
            refreshAll();
          }}
        />
      ) : null}
      <MarkDayDialog
        open={markDay !== null}
        onOpenChange={(next) => (next ? null : setMarkDay(null))}
        initialEmployees={markDay?.employees}
        initialDate={markDay?.date}
        onRecorded={refreshAll}
      />
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
