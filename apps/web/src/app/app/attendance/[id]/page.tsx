"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { AttendanceStatusBadge } from "@/components/attendance/attendance-status-badge";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { RegularizationRequestDialog } from "@/components/regularization/regularization-request-dialog";
import { Badge } from "@/components/ui/badge";
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
import type { AttendanceDay } from "@/lib/attendance/types";
import { formatDateTime, formatMinutes } from "@/lib/attendance/format";
import { usePermissions } from "@/lib/auth/use-permissions";

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

  const [day, setDay] = useState<AttendanceDay | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [regularizeOpen, setRegularizeOpen] = useState(false);
  const [recomputing, setRecomputing] = useState(false);
  const [showSnapshot, setShowSnapshot] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<AttendanceDay>(`/attendance/days/${params.id}`);
      setDay(data);
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
        title="Attendance day"
        description={day ? `${day.attendance_date} — ${day.timezone}` : undefined}
        actions={
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" onClick={() => router.push("/app/attendance")}>
              Back to attendance
            </Button>
            {day && can("ATTENDANCE.REGULARIZATION_REQUEST_ON_BEHALF") ? (
              <Button type="button" variant="outline" onClick={() => setRegularizeOpen(true)}>
                Regularize
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
          <div className="flex flex-wrap items-center gap-2">
            <AttendanceStatusBadge status={day.attendance_status} />
            {day.is_late ? <Badge variant="warning">Late</Badge> : null}
            {day.is_early_out ? <Badge variant="warning">Early departure</Badge> : null}
            {day.is_overtime ? <Badge variant="info">Overtime</Badge> : null}
            {day.is_regularized ? <Badge variant="secondary">Regularized</Badge> : null}
            {day.is_pending_approval ? <Badge variant="warning">Pending approval</Badge> : null}
            {day.worked_on_holiday ? <Badge variant="info">Worked on holiday</Badge> : null}
            {day.worked_on_weekly_off ? <Badge variant="info">Worked on weekly off</Badge> : null}
            {day.missing_punch ? <Badge variant="danger">Missing punch</Badge> : null}
            {day.is_locked ? <Badge variant="outline">Locked</Badge> : null}
          </div>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Schedule</h2>
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field label="Calendar day type" value={day.calendar_day_type ?? "—"} />
                <Field label="Holiday" value={day.holiday_name ?? "—"} />
                <Field
                  label="Scheduled"
                  value={
                    day.scheduled_start && day.scheduled_end
                      ? `${formatDateTime(day.scheduled_start)} – ${formatDateTime(day.scheduled_end)}`
                      : "—"
                  }
                />
                <Field label="Scheduled minutes" value={formatMinutes(day.scheduled_minutes)} />
                <Field label="Shift ID" value={day.shift_id ?? "—"} />
                <Field label="Shift version" value={day.shift_version_id ?? "—"} />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Punches & worked time</h2>
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field label="First in" value={formatDateTime(day.actual_first_in)} />
                <Field label="Last out" value={formatDateTime(day.actual_last_out)} />
                <Field label="Worked minutes" value={formatMinutes(day.worked_minutes)} />
                <Field label="Unpaid break" value={formatMinutes(day.unpaid_break_minutes)} />
                <Field label="Paid break" value={formatMinutes(day.paid_break_minutes)} />
                <Field label="Excess break" value={formatMinutes(day.excess_break_minutes)} />
                <Field label="Late" value={formatMinutes(day.late_minutes)} />
                <Field label="Early departure" value={formatMinutes(day.early_departure_minutes)} />
                <Field label="Late classification" value={day.late_classification ?? "—"} />
              </dl>
              {day.breaks.length > 0 ? (
                <div className="mt-4 overflow-x-auto rounded-md border border-border">
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
                          <td className="px-3 py-2">{formatDateTime(brk.break_start)}</td>
                          <td className="px-3 py-2">{formatDateTime(brk.break_end)}</td>
                          <td className="px-3 py-2">{formatMinutes(brk.minutes)}</td>
                          <td className="px-3 py-2">{brk.is_paid ? "Yes" : "No"}</td>
                          <td className="px-3 py-2">{brk.is_excess ? "Yes" : "No"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Overtime & pay facts</h2>
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field label="OT detected" value={formatMinutes(day.ot_minutes_detected)} />
                <Field label="OT approved" value={formatMinutes(day.ot_minutes_approved)} />
                <Field label="OT classification" value={day.ot_classification ?? "—"} />
                <Field label="Comp-off earned" value={formatMinutes(day.comp_off_minutes_earned)} />
                <Field label="Paid day fraction" value={day.paid_day_fraction} />
                <Field label="LOP fraction" value={day.lop_fraction} />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Calculation & audit</h2>
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field label="Calculation version" value={day.calculation_version} />
                <Field label="Calculated at" value={formatDateTime(day.calculated_at)} />
                <Field label="Attendance policy version" value={day.attendance_policy_version_id ?? "—"} />
                <Field label="Overtime policy version" value={day.overtime_policy_version_id ?? "—"} />
                <Field label="Regularization policy version" value={day.regularization_policy_version_id ?? "—"} />
                <Field label="Locked at" value={day.is_locked ? formatDateTime(day.locked_at) : "—"} />
              </dl>
              <div className="mt-4">
                <Button type="button" variant="outline" size="sm" onClick={() => setShowSnapshot((v) => !v)}>
                  {showSnapshot ? "Hide" : "Show"} computation snapshot
                </Button>
                {showSnapshot ? (
                  <pre className="mt-3 max-h-96 overflow-auto rounded-md border border-border bg-surface-secondary p-3 text-xs text-foreground-secondary">
                    {JSON.stringify(day.computation_snapshot, null, 2)}
                  </pre>
                ) : null}
              </div>
            </CardContent>
          </Card>
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
        <RegularizationRequestDialog
          open={regularizeOpen}
          onOpenChange={setRegularizeOpen}
          mode="ON_BEHALF"
          employeeId={day.employee_id}
          attendanceDate={day.attendance_date}
          onCreated={() =>
            toast({ title: "Regularization request submitted", variant: "success" })
          }
        />
      ) : null}
    </div>
  );
}
