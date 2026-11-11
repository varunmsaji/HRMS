"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";

import { DayRegularization } from "@/components/attendance/day/day-regularization";
import { DaySummaryCard } from "@/components/attendance/day/day-summary";
import { DayTimeline } from "@/components/attendance/day/day-timeline";
import { KeepLeaveDialog } from "@/components/attendance/keep-leave-dialog";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { RegularizationRequestDialog } from "@/components/regularization/regularization-request-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { buildTimeline, type BreakEventLite } from "@/lib/attendance/day-detail";
import { employeeName as nameOf, type EmployeeLite } from "@/lib/attendance/dashboard";
import type { AttendanceDay, Punch } from "@/lib/attendance/types";
import { useAuth } from "@/lib/auth/auth-context";
import type { RegularizationRequest } from "@/lib/regularization/types";
import { formatDateTime, formatMinutes, zoneLabel } from "@/lib/attendance/format";
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { LeaveDayProjection } from "@/lib/leave-projection/types";

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-foreground">{value}</dd>
    </div>
  );
}

export default function AttendanceDayDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { toast } = useToast();
  const { can } = usePermissions();
  const datePattern = useCompanyDatePattern();

  const [day, setDay] = useState<AttendanceDay | null>(null);
  const [leaveProjections, setLeaveProjections] = useState<LeaveDayProjection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [regularizeOpen, setRegularizeOpen] = useState(false);
  const [recomputing, setRecomputing] = useState(false);
  const [keepLeaveOpen, setKeepLeaveOpen] = useState(false);
  const [showSnapshot, setShowSnapshot] = useState(false);
  const { user } = useAuth();
  const [employee, setEmployee] = useState<EmployeeLite | null>(null);
  const [shiftName, setShiftName] = useState<string | null>(null);
  const [punches, setPunches] = useState<Punch[] | null>(null);
  const [breakEvents, setBreakEvents] = useState<BreakEventLite[]>([]);
  const [requests, setRequests] = useState<RegularizationRequest[] | null>(null);
  const [neighbours, setNeighbours] = useState<{ prev: string | null; next: string | null }>({ prev: null, next: null });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<AttendanceDay>(`/attendance/days/${params.id}`);
      setDay(data);
      // Best-effort — a caller without ATTENDANCE.VIEW-equivalent leave-projection visibility
      // (or simply no projections for this day) just sees an empty overlay/provenance section,
      // never a blocking error on the attendance day itself.
      try {
        const projectionParams = new URLSearchParams({
          employee_id: data.employee_id,
          date_from: data.attendance_date,
          date_to: data.attendance_date,
        });
        const projections = await apiClient.get<LeaveDayProjection[]>(
          `/leave-projections?${projectionParams.toString()}`,
        );
        setLeaveProjections(projections);
      } catch {
        setLeaveProjections([]);
      }
    } catch (err) {
      setDay(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  // Everything below is context for the day; each piece is best-effort and never blocks the page.
  const dayId = day?.id;
  const dayEmployee = day?.employee_id;
  const dayDate = day?.attendance_date;
  const dayShift = day?.shift_id;
  useEffect(() => {
    if (!dayId || !dayEmployee || !dayDate) return;
    let cancelled = false;
    const shift = (d: string, n: number) => {
      const t = new Date(`${d}T00:00:00Z`);
      t.setUTCDate(t.getUTCDate() + n);
      return t.toISOString().slice(0, 10);
    };
    apiClient.get<EmployeeLite>(`/employees/${dayEmployee}`).then((e) => !cancelled && e && !Array.isArray(e) && setEmployee(e)).catch(() => {});
    if (dayShift) {
      apiClient
        .get<{ id: string; name: string }[]>("/shifts")
        .then((list) => {
          const match = Array.isArray(list) ? list.find((s) => s.id === dayShift) : undefined;
          if (!cancelled && match) setShiftName(match.name);
        })
        .catch(() => {});
    }
    const q = (o: Record<string, string>) => new URLSearchParams(o).toString();
    apiClient
      .get<Punch[]>(`/attendance/punches?${q({ employee_id: dayEmployee, date_from: dayDate, date_to: shift(dayDate, 1) })}`)
      .then((list) => !cancelled && setPunches(Array.isArray(list) ? list : []))
      .catch(() => !cancelled && setPunches([]));
    apiClient
      .get<{ events: BreakEventLite[] }>(`/attendance/breaks/day?${q({ employee_id: dayEmployee, date: dayDate })}`)
      .then((d) => !cancelled && Array.isArray(d?.events) && setBreakEvents(d.events))
      .catch(() => {});
    apiClient
      .get<RegularizationRequest[]>(`/regularizations?${q({ employee_id: dayEmployee })}`)
      .then((list) => !cancelled && Array.isArray(list) && setRequests(list.filter((r) => r.attendance_date === dayDate)))
      .catch(() => {});
    apiClient
      .get<AttendanceDay[]>(`/attendance/days?${q({ employee_id: dayEmployee, date_from: shift(dayDate, -1), date_to: shift(dayDate, 1) })}`)
      .then((list) => {
        if (cancelled || !Array.isArray(list)) return;
        setNeighbours({
          prev: list.find((d) => d.attendance_date === shift(dayDate, -1))?.id ?? null,
          next: list.find((d) => d.attendance_date === shift(dayDate, 1))?.id ?? null,
        });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [dayId, dayEmployee, dayDate, dayShift]);

  const timeline = useMemo(
    () => (day && punches !== null ? buildTimeline(day, punches, breakEvents) : null),
    [day, punches, breakEvents],
  );
  const isOwnDay = Boolean(day && user?.employee_id && day.employee_id === user.employee_id);
  // The API treats a request naming the caller's own employee as a self request, so on-behalf
  // is never offered on the viewer's own day.
  const requestMode: "SELF" | "ON_BEHALF" | null = !day
    ? null
    : isOwnDay
      ? can("ATTENDANCE.REGULARIZATION_REQUEST")
        ? "SELF"
        : null
      : can("ATTENDANCE.REGULARIZATION_REQUEST_ON_BEHALF")
        ? "ON_BEHALF"
        : null;

  async function handleRecompute() {
    setRecomputing(true);
    try {
      const data = await apiClient.post<AttendanceDay>(`/attendance/days/${params.id}/recompute`);
      setDay(data);
      setConfirmOpen(false);
      toast({ title: "Attendance day recomputed", variant: "success" });
    } catch (err) {
      toast({ title: "Could not recompute", description: describeApiError(err), variant: "danger" });
    } finally {
      setRecomputing(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={day && employee ? `${nameOf(employee, day.employee_id)} — attendance` : "Attendance day"}
        description={
          day
            ? // `DEC-TZ-06`/`CD-3` (SELECTED) — labels the zone every timestamp on this page is
              // actually rendered in (`day.timezone`, the WD-06-resolved zone this day was
              // COMPUTED in), not the viewer's browser zone. For India V1 this always reads
              // "Asia/Kolkata (IST)"; the day it doesn't (a non-India branch, not in V1 scope)
              // this label is what keeps the page honest about which clock it's showing.
              `${formatCompanyDate(day.attendance_date, datePattern)} — ${day.timezone} (${zoneLabel(day.timezone)})`
            : undefined
        }
        actions={
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" onClick={() => router.push("/app/attendance")}>
              Back to attendance
            </Button>
            {day &&
            can("ATTENDANCE.RECOMPUTE") &&
            day.work_on_leave_flagged &&
            !day.work_on_leave_resolution &&
            !day.is_locked ? (
              <Button type="button" variant="outline" onClick={() => setKeepLeaveOpen(true)}>
                Keep leave
              </Button>
            ) : null}
            {day && can("ATTENDANCE.RECOMPUTE") ? (
              <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)} disabled={day.is_locked}>
                Recompute
              </Button>
            ) : null}
          </div>
        }
      />

      {loading ? <LoadingState label="Loading attendance day…" fullPage /> : null}
      {error && !loading ? (
        <ErrorState
          message={
            error.status === 404
              ? "This attendance day was not found, or you don't have access to it."
              : error.message
          }
          onRetry={() => void load()}
        />
      ) : null}

      {!loading && !error && day ? (
        <div className="space-y-6">
          <DaySummaryCard
            day={day}
            employeeName={employee ? nameOf(employee, day.employee_id) : null}
            employeeCode={employee?.employee_code ?? null}
            shiftName={shiftName}
            prevDayId={neighbours.prev}
            nextDayId={neighbours.next}
          />

          <div className="grid gap-6 lg:grid-cols-2">
            <DayTimeline items={timeline} timezone={day.timezone} />
            <div className="space-y-6">
              <DayRegularization
                requests={requests}
                canRequest={requestMode !== null}
                needsCorrection={day.missing_punch || day.is_late || day.is_early_out || day.attendance_status === "INCOMPLETE"}
                onRequest={() => setRegularizeOpen(true)}
              />
              <Card>
                <CardContent className="pt-6">
                  <h2 className="mb-4 text-base font-semibold text-foreground">Time summary</h2>
                  <dl className="grid grid-cols-2 gap-4">
                    <Field label="Worked" value={formatMinutes(day.worked_minutes)} />
                    <Field label="Scheduled" value={formatMinutes(day.scheduled_minutes)} />
                    <Field label="Late" value={day.is_late ? formatMinutes(day.late_minutes) : "—"} />
                    <Field label="Early departure" value={day.is_early_out ? formatMinutes(day.early_departure_minutes) : "—"} />
                    <Field label="Paid break" value={formatMinutes(day.paid_break_minutes)} />
                    <Field label="Unpaid break" value={formatMinutes(day.unpaid_break_minutes)} />
                    <Field label="Excess break" value={day.excess_break_minutes > 0 ? formatMinutes(day.excess_break_minutes) : "—"} />
                    <Field
                      label="Overtime"
                      value={
                        day.ot_minutes_detected > 0
                          ? `${formatMinutes(day.ot_minutes_detected)} (${formatMinutes(day.ot_minutes_approved)} approved)`
                          : "—"
                      }
                    />
                  </dl>
                </CardContent>
              </Card>
            </div>
          </div>

          {day.breaks.length > 0 ? (
            <Card>
              <CardContent className="pt-6">
                <h2 className="mb-4 text-base font-semibold text-foreground">Breaks</h2>
                <div className="overflow-x-auto rounded-md border border-border">
                  <table className="w-full text-sm">
                    <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">Start</th>
                        <th className="px-3 py-2 text-left font-medium">End</th>
                        <th className="px-3 py-2 text-left font-medium">Minutes</th>
                        <th className="px-3 py-2 text-left font-medium">Paid</th>
                        <th className="px-3 py-2 text-left font-medium">Excess</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {day.breaks.map((brk) => (
                        <tr key={brk.id}>
                          <td className="px-3 py-2">{formatDateTime(brk.break_start, day.timezone)}</td>
                          <td className="px-3 py-2">{formatDateTime(brk.break_end, day.timezone)}</td>
                          <td className="px-3 py-2">{formatMinutes(brk.minutes)}</td>
                          <td className="px-3 py-2">{brk.is_paid ? "Yes" : "No"}</td>
                          <td className="px-3 py-2">{brk.is_excess ? "Yes" : "No"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          ) : null}

          {leaveProjections.length > 0 ? (
            <Card>
              <CardContent className="pt-6">
                <h2 className="mb-4 text-sm font-medium text-foreground">
                  Approved leave on this date
                </h2>
                <div className="overflow-x-auto rounded-md border border-border">
                  <table className="w-full text-sm">
                    <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">Leave</th>
                        <th className="px-3 py-2 text-left font-medium">Fraction</th>
                        <th className="px-3 py-2 text-left font-medium">Half</th>
                        <th className="px-3 py-2 text-left font-medium">Paid</th>
                        <th className="px-3 py-2 text-left font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {leaveProjections.map((projection) => (
                        <tr key={projection.id}>
                          <td className="px-3 py-2">
                            <Link
                              href={`/app/leave-applications/${projection.leave_application_id}`}
                              className="font-medium text-primary hover:underline"
                            >
                              {projection.leave_type_code ?? "Leave"} — view application
                            </Link>
                          </td>
                          <td className="px-3 py-2">{projection.fraction}</td>
                          <td className="px-3 py-2">{projection.half ?? "—"}</td>
                          <td className="px-3 py-2">{projection.is_paid ? "Yes" : "No"}</td>
                          <td className="px-3 py-2">{projection.status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-xs text-foreground-muted">
                  Provenance only — Attendance does not own these facts. They mirror what Leave
                  published as approved; Leave, not Attendance, owns entitlement/balance/approval.
                </p>
              </CardContent>
            </Card>
          ) : null}

          <details className="group rounded-2xl border border-border bg-surface shadow-elevation-1">
            <summary className="cursor-pointer select-none px-6 py-4 text-base font-semibold text-foreground">
              Calculation details
              <span className="ml-2 text-xs font-normal text-foreground-muted">for HR and support</span>
            </summary>
            <div className="space-y-6 px-6 pb-6">
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field label="Calendar day type" value={day.calendar_day_type ?? "—"} />
                <Field label="Holiday" value={day.holiday_name ?? "—"} />
                <Field label="Shift" value={shiftName ?? day.shift_id ?? "—"} />
                <Field label="Late classification" value={day.late_classification ?? "—"} />
                <Field label="OT classification" value={day.ot_classification ?? "—"} />
                <Field label="Comp-off earned" value={formatMinutes(day.comp_off_minutes_earned)} />
                <Field label="Paid day fraction" value={day.paid_day_fraction} />
                <Field label="Leave fraction" value={day.leave_fraction} />
                <Field label="Weekly-off fraction" value={day.weekly_off_fraction} />
                <Field label="Unpaid off fraction" value={day.unpaid_off_fraction} />
                <Field label="LOP fraction" value={day.lop_fraction} />
                {day.work_on_leave_resolution ? (
                  <Field
                    label="Work-on-leave decision"
                    value={`Leave kept — ${day.work_on_leave_resolution_reason ?? ""}`}
                  />
                ) : null}
                <Field label="Calculation version" value={day.calculation_version} />
                <Field label="Calculated at" value={formatDateTime(day.calculated_at, day.timezone)} />
                <Field label="Locked at" value={day.is_locked ? formatDateTime(day.locked_at, day.timezone) : "—"} />
                <Field label="Shift version" value={day.shift_version_id ?? "—"} />
                <Field label="Attendance policy version" value={day.attendance_policy_version_id ?? "—"} />
                <Field label="Overtime policy version" value={day.overtime_policy_version_id ?? "—"} />
                <Field label="Regularization policy version" value={day.regularization_policy_version_id ?? "—"} />
              </dl>
              <div>
                <Button type="button" variant="outline" size="sm" onClick={() => setShowSnapshot((v) => !v)}>
                  {showSnapshot ? "Hide" : "Show"} computation snapshot
                </Button>
                {showSnapshot ? (
                  <pre className="mt-3 max-h-96 overflow-auto rounded-md border border-border bg-surface-secondary p-3 text-xs text-foreground-secondary">
                    {JSON.stringify(day.computation_snapshot, null, 2)}
                  </pre>
                ) : null}
              </div>
            </div>
          </details>
        </div>
      ) : null}

      <Dialog open={confirmOpen} onOpenChange={(open) => (!recomputing ? setConfirmOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Recompute this attendance day?</DialogTitle>
            <DialogDescription>
              This re-resolves the applicable policy/shift/calendar versions as of the attendance date
              and fully replaces the derived fields. The previous computation is not otherwise
              recoverable outside the audit log.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setConfirmOpen(false)} disabled={recomputing}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleRecompute()} disabled={recomputing}>
              {recomputing ? "Recomputing…" : "Recompute"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {day ? (
        <KeepLeaveDialog open={keepLeaveOpen} onOpenChange={setKeepLeaveOpen} day={day} onDone={setDay} />
      ) : null}

      {day ? (
        <RegularizationRequestDialog
          open={regularizeOpen}
          onOpenChange={setRegularizeOpen}
          mode={requestMode ?? "ON_BEHALF"}
          employeeId={day.employee_id}
          attendanceDate={day.attendance_date}
          onCreated={(created) => {
            setRequests((prev) => [created, ...(prev ?? [])]);
            toast({ title: "Regularization request submitted", variant: "success" });
          }}
        />
      ) : null}
    </div>
  );
}
