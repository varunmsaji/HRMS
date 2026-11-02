"use client";

import { RosterTabs } from "@/components/shift-roster/roster-tabs";
import { ArrowLeftRight, ChevronLeft, ChevronRight, Plus, Users } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { useToast } from "@/components/common/toast";
import { RosterEntryDialog } from "@/components/shift-roster/roster-entry-dialog";
import { RequestSwapDialog } from "@/components/shift-roster/request-swap-dialog";
import { SwapRequests } from "@/components/shift-roster/swap-requests";
import { WeeklyOperationalSchedule } from "@/components/shift-roster/weekly-operational-schedule";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Progress } from "@/components/ui/progress";
import { TableSkeleton } from "@/components/ui/skeleton";
import { isAbortError, useLatestRequest } from "@/hooks/use-latest-request";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  addDays,
  mondayOf,
  weekLabel,
  type SwapRequest,
  type SwapResponse,
  type WeeklySchedule,
} from "@/lib/shift-roster/schedule";
import { cn } from "@/lib/utils";

interface NamedOption {
  id: string;
  name: string;
}

function Kpi({
  label,
  badge,
  badgeTone,
  value,
  note,
  progress,
}: {
  label: string;
  badge?: string;
  badgeTone?: "success" | "info" | "warning";
  value: ReactNode;
  note: string;
  progress?: number;
}) {
  const tones = {
    success: "bg-success-subtle text-success",
    info: "bg-info-subtle text-info",
    warning: "bg-warning-subtle text-warning",
  } as const;
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 shadow-elevation-1">
      <div className="flex items-start justify-between gap-2">
        <p className="text-2xs font-semibold uppercase tracking-wider text-foreground-muted">{label}</p>
        {badge ? (
          <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", tones[badgeTone ?? "success"])}>
            {badge}
          </span>
        ) : null}
      </div>
      <p className="mt-3 text-3xl font-bold tabular-nums tracking-tight text-foreground">{value}</p>
      <p className="mt-1 text-xs text-foreground-secondary">{note}</p>
      {progress !== undefined ? (
        <Progress value={progress} className="mt-4 h-1.5" aria-label={label} />
      ) : null}
    </div>
  );
}

/** Weekly shift schedule and coverage (`GET /v1/rosters/weekly-schedule`) with the pending
 * shift-swap queue (`/v1/rosters/swap-requests`). All figures come from stored roster data. */
export default function ShiftSchedulePage() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const { toast } = useToast();
  const canManage = can("ATTENDANCE.ROSTER_MANAGE");
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");

  const [weekStart, setWeekStart] = useState(() => mondayOf(today));
  const [branchId, setBranchId] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [branches, setBranches] = useState<NamedOption[]>([]);
  const [departments, setDepartments] = useState<NamedOption[]>([]);

  const [schedule, setSchedule] = useState<WeeklySchedule | null>(null);
  const [swaps, setSwaps] = useState<SwapRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [assignOpen, setAssignOpen] = useState(false);
  const [swapOpen, setSwapOpen] = useState(false);
  const meEmployeeId = user?.employee_id ?? null;
  const beginRequest = useLatestRequest();

  useEffect(() => {
    void apiClient.get<NamedOption[]>("/branches").then(setBranches).catch(() => setBranches([]));
    void apiClient.get<NamedOption[]>("/departments").then(setDepartments).catch(() => setDepartments([]));
  }, []);

  const load = useCallback(async () => {
    const request = beginRequest();
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ week_start: weekStart });
    if (branchId) params.set("branch_id", branchId);
    if (departmentId) params.set("department_id", departmentId);
    try {
      const [sched, pending] = await Promise.all([
        apiClient.get<WeeklySchedule>(`/rosters/weekly-schedule?${params}`, { signal: request.signal }),
        apiClient.get<SwapRequest[]>("/rosters/swap-requests?status=PENDING", { signal: request.signal }),
      ]);
      if (!request.isCurrent()) return;
      setSchedule(sched);
      setSwaps(pending);
    } catch (err) {
      if (isAbortError(err) || !request.isCurrent()) return;
      setSchedule(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      if (request.isCurrent()) setLoading(false);
    }
  }, [beginRequest, weekStart, branchId, departmentId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(swap: SwapRequest, approve: boolean) {
    try {
      await apiClient.post<SwapRequest>(
        `/rosters/swap-requests/${swap.id}/${approve ? "approve" : "decline"}`,
        {},
      );
      toast({
        title: approve ? `Swap ${swap.reference} approved` : `Swap ${swap.reference} declined`,
        variant: "success",
      });
      await load();
    } catch (err) {
      toast({ title: "Could not save the decision", description: describeApiError(err), variant: "danger" });
    }
  }

  async function respond(swap: SwapRequest, response: SwapResponse) {
    try {
      await apiClient.post<SwapRequest>(`/rosters/swap-requests/${swap.id}/${response}`, {});
      toast({
        title:
          response === "consent"
            ? `You agreed to swap ${swap.reference}`
            : `Swap ${swap.reference} ${swap.requester.employee_id === meEmployeeId ? "withdrawn" : "turned down"}`,
        variant: "success",
      });
      await load();
    } catch (err) {
      toast({ title: "Could not update the swap", description: describeApiError(err), variant: "danger" });
    }
  }

  const totals = schedule?.totals;
  const thisWeek = weekStart === mondayOf(today);
  const scheduledPct = useMemo(
    () => (totals && totals.active_headcount > 0 ? Math.round((100 * totals.rostered_staff) / totals.active_headcount) : 0),
    [totals],
  );

  return (
    <div className="space-y-6">
      <RosterTabs active="coverage" />

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Shift Rostering &amp; Schedule Coverage</h1>
          <p className="mt-1 max-w-md text-sm text-foreground-secondary">
            Manage shift rotations, department schedules, and weekly coverage thresholds
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center rounded-lg border border-border bg-surface">
            <Button type="button" variant="ghost" size="sm" aria-label="Previous week" onClick={() => setWeekStart(addDays(weekStart, -7))}>
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </Button>
            <span className="px-2 text-sm font-medium text-foreground">
              {schedule ? weekLabel(schedule.week_start, schedule.week_end) : weekLabel(weekStart, addDays(weekStart, 6))}
            </span>
            <Button type="button" variant="ghost" size="sm" aria-label="Next week" onClick={() => setWeekStart(addDays(weekStart, 7))}>
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Button>
            {thisWeek ? (
              <span className="mr-2 rounded bg-primary-subtle px-2 py-0.5 text-[11px] font-semibold text-primary">This Week</span>
            ) : (
              <Button type="button" variant="ghost" size="sm" onClick={() => setWeekStart(mondayOf(today))}>
                This Week
              </Button>
            )}
          </div>
          <NativeSelect
            aria-label="Department"
            value={departmentId}
            onChange={(e) => setDepartmentId(e.target.value)}
            className="w-auto"
          >
            <option value="">All Departments ({departments.length})</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect aria-label="Branch" value={branchId} onChange={(e) => setBranchId(e.target.value)} className="w-auto">
            <option value="">All Branches ({branches.length})</option>
            {branches.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </NativeSelect>
          {meEmployeeId ? (
            <Button type="button" variant="outline" onClick={() => setSwapOpen(true)}>
              <ArrowLeftRight className="h-4 w-4" aria-hidden="true" />
              Request a swap
            </Button>
          ) : null}
          {canManage ? (
            <Button type="button" onClick={() => setAssignOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              Assign Shift
            </Button>
          ) : null}
        </div>
      </div>

      {loading && !schedule ? (
        <div role="status" aria-label="Loading schedule">
          <TableSkeleton rows={6} columns={8} />
          <span className="sr-only">Loading schedule…</span>
        </div>
      ) : null}
      {error && !loading ? (
        <ErrorState
          message={error.status === 403 ? "You do not have permission to view the roster." : error.message}
          onRetry={() => void load()}
        />
      ) : null}

      <details className="rounded-lg border border-border bg-surface-secondary px-4 py-3 text-sm text-foreground-secondary" open>
        <summary className="cursor-pointer font-medium text-foreground">What is schedule coverage?</summary>
        <div className="mt-2 space-y-2">
          <p>
            Coverage tells you whether enough people are scheduled to work each shift. Every shift can have a minimum number of staff it needs.
            If fewer people are rostered than that minimum on a given day, that day is short-staffed.
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li><strong className="text-foreground">Rostered staff</strong> – how many of your active employees have a shift assigned this week.</li>
            <li><strong className="text-foreground">Coverage efficiency</strong> – the share of shift days that have at least their minimum number of people. 100% means nobody is short.</li>
            <li><strong className="text-foreground">Night shift coverage</strong> – how many people are scheduled on night shifts this week.</li>
            <li><strong className="text-foreground">Shift swap requests</strong> – employees who asked to swap shifts and are waiting for a manager&apos;s decision.</li>
          </ul>
          <p>
            The weekly table below shows who works which shift on each day, and flags days that fall under the minimum. Use <em>Assign Shift</em> to fill a gap, or
            switch to <em>Roster entries</em> to edit individual assignments.
          </p>
        </div>
      </details>

      {schedule && totals ? (
        <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi
              label="Rostered staff"
              badge={`${scheduledPct}% scheduled`}
              badgeTone={scheduledPct >= 100 ? "success" : "warning"}
              value={totals.rostered_staff.toLocaleString()}
              note={`${totals.rostered_staff.toLocaleString()} of ${totals.active_headcount.toLocaleString()} active headcount assigned`}
              progress={scheduledPct}
            />
            <Kpi
              label="Coverage efficiency"
              badge={
                totals.coverage_pct === null ? undefined : totals.cells_below_target === 0 ? "Optimal" : "Needs attention"
              }
              badgeTone={totals.cells_below_target === 0 ? "success" : "warning"}
              value={totals.coverage_pct === null ? "—" : `${totals.coverage_pct}%`}
              note={
                totals.coverage_pct === null
                  ? "No shift has a minimum staffing target"
                  : totals.cells_below_target === 0
                    ? `All minimum staffing thresholds met across ${totals.shifts_with_target} shifts`
                    : `${totals.cells_below_target} shift ${totals.cells_below_target === 1 ? "day is" : "days are"} below its minimum`
              }
              progress={totals.coverage_pct ?? 0}
            />
            <Kpi
              label="Night shift coverage"
              badge={totals.night_shift_count > 0 ? "Active" : undefined}
              badgeTone="info"
              value={`${totals.night_staff} Staff`}
              note={
                totals.night_shift_count > 0
                  ? `Rostered across ${totals.night_shift_count} night ${totals.night_shift_count === 1 ? "shift" : "shifts"} this week`
                  : "No night shift is configured"
              }
              progress={totals.night_staff > 0 ? 100 : 0}
            />
            <Kpi
              label="Shift swap requests"
              badge={totals.pending_swaps > 0 ? "Pending" : undefined}
              badgeTone="warning"
              value={totals.pending_swaps}
              note={totals.pending_swaps > 0 ? "Peer swaps awaiting a supervisor decision" : "Nothing is waiting for a decision"}
              progress={totals.pending_swaps > 0 ? 60 : 0}
            />
          </div>

          {totals.rostered_staff === 0 ? (
            <EmptyState
              icon={Users}
              title="No one is rostered for this week."
              description="Publish roster entries for this week and they will appear here."
            />
          ) : (
            <WeeklyOperationalSchedule schedule={schedule} today={today} />
          )}

          <SwapRequests swaps={swaps} canDecide={canManage} meEmployeeId={meEmployeeId} onDecide={decide} onRespond={respond} />
        </>
      ) : null}

      <RosterEntryDialog
        open={assignOpen}
        onOpenChange={setAssignOpen}
        roster={null}
        onSaved={() => void load()}
      />
      <RequestSwapDialog open={swapOpen} onOpenChange={setSwapOpen} today={today} onRequested={() => void load()} />
    </div>
  );
}
