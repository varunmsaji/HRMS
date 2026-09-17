"use client";

import { CalendarClock } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AttendanceStatusBadge } from "@/components/attendance/attendance-status-badge";
import { PunchEntryDialog } from "@/components/attendance/punch-entry-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import type { AttendanceDay, Punch } from "@/lib/attendance/types";
import { businessToday, formatClockTime, formatMinutes } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";

interface EmployeeAttendancePanelProps {
  employeeId: string;
  employeeLabel: string;
}

function daysAgoIso(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

/** Employee-scoped attendance history — architecture §26 "Employee attendance view": shift,
 * scheduled time, punches, worked hours, breaks, late/early, overtime, status, exceptions for a
 * date range. `GET /v1/attendance/days` is already data-scope filtered server-side (SELF sees
 * only their own row even if this panel is reused on someone else's employee page), so this
 * component does no additional client-side filtering. */
export function EmployeeAttendancePanel({ employeeId, employeeLabel }: EmployeeAttendancePanelProps) {
  const { user } = useAuth();
  const { toast } = useToast();
  const { can } = usePermissions();

  const [dateFrom, setDateFrom] = useState(daysAgoIso(6));
  const [dateTo, setDateTo] = useState(businessToday(user?.company_timezone ?? "Asia/Kolkata"));
  const [days, setDays] = useState<AttendanceDay[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [punchOpen, setPunchOpen] = useState(false);
  const [calculating, setCalculating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<AttendanceDay[]>(
        `/attendance/days?employee_id=${employeeId}&date_from=${dateFrom}&date_to=${dateTo}`,
      );
      setDays(data.slice().sort((a, b) => b.attendance_date.localeCompare(a.attendance_date)));
    } catch (err) {
      setDays(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [employeeId, dateFrom, dateTo]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCalculateToday() {
    setCalculating(true);
    try {
      // `NEW-02` (execution gate §9.3, `ED-2`) — `date` is no longer sent at all. It used to be
      // `todayIso()`, the browser's UTC calendar date: between 00:00 and 05:29 IST that is one
      // day BEHIND the correct India business date, so "Calculate today" would calculate
      // *yesterday* for that entire window. The server now defaults to `business_today()` when
      // `date` is omitted, so the client no longer computes "today" itself at all.
      await apiClient.post(`/attendance/days/calculate?employee_id=${employeeId}`);
      toast({ title: "Today's attendance calculated", variant: "success" });
      await load();
    } catch (err) {
      toast({
        title: "Could not calculate attendance",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setCalculating(false);
    }
  }

  function onPunchRecorded(_punch: Punch) {
    void load();
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <FormField id="att-panel-from" label="From" className="w-40">
            <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </FormField>
          <FormField id="att-panel-to" label="To" className="w-40">
            <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </FormField>
        </div>
        <div className="flex items-center gap-2">
          {can("ATTENDANCE.VIEW_ALL") ? (
            <Button type="button" variant="outline" onClick={() => void handleCalculateToday()} disabled={calculating}>
              {calculating ? "Calculating…" : "Calculate today"}
            </Button>
          ) : null}
          {can("ATTENDANCE.PUNCH") || can("ATTENDANCE.PUNCH_ON_BEHALF") ? (
            <Button type="button" onClick={() => setPunchOpen(true)}>
              Record punch
            </Button>
          ) : null}
        </div>
      </div>

      {loading ? <LoadingState label="Loading attendance…" /> : null}
      {error && !loading ? (
        <ErrorState
          message={
            error.status === 403
              ? "You do not have permission to view this employee's attendance."
              : error.message
          }
          onRetry={() => void load()}
        />
      ) : null}
      {!loading && !error && days && days.length === 0 ? (
        <EmptyState
          icon={CalendarClock}
          title="No attendance days in this range."
          description="Record a punch, or widen the date range."
        />
      ) : null}

      {!loading && !error && days && days.length > 0 ? (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Date</th>
                <th className="px-3 py-2 text-left font-medium">Status</th>
                <th className="px-3 py-2 text-left font-medium">Scheduled</th>
                <th className="px-3 py-2 text-left font-medium">First in / last out</th>
                <th className="px-3 py-2 text-left font-medium">Worked</th>
                <th className="px-3 py-2 text-left font-medium">Late / Early</th>
                <th className="px-3 py-2 text-left font-medium">OT</th>
                <th className="px-3 py-2 text-left font-medium">Exceptions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {days.map((day) => (
                <tr key={day.id} className="hover:bg-accent">
                  <td className="px-3 py-2">
                    <Link href={`/app/attendance/${day.id}`} className="font-medium text-foreground hover:underline">
                      {day.attendance_date}
                    </Link>
                  </td>
                  <td className="px-3 py-2">
                    <AttendanceStatusBadge status={day.attendance_status} />
                  </td>
                  <td className="px-3 py-2 text-foreground-secondary">
                    {day.scheduled_start && day.scheduled_end
                      ? `${formatClockTime(day.scheduled_start, day.timezone)}–${formatClockTime(day.scheduled_end, day.timezone)}`
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-foreground-secondary">
                    {formatClockTime(day.actual_first_in, day.timezone)}–{formatClockTime(day.actual_last_out, day.timezone)}
                  </td>
                  <td className="px-3 py-2 text-foreground-secondary">{formatMinutes(day.worked_minutes)}</td>
                  <td className="px-3 py-2 text-foreground-secondary">
                    {day.is_late ? formatMinutes(day.late_minutes) : "—"}
                    {day.is_early_out ? ` / ${formatMinutes(day.early_departure_minutes)}` : ""}
                  </td>
                  <td className="px-3 py-2 text-foreground-secondary">
                    {day.is_overtime ? formatMinutes(day.ot_minutes_detected) : "—"}
                  </td>
                  <td className="px-3 py-2 text-foreground-secondary">
                    {day.missing_punch ? "Missing punch " : ""}
                    {day.attendance_status === "CONFIG_ERROR" ? "Config error " : ""}
                    {day.is_pending_approval ? "Pending approval " : ""}
                    {!day.missing_punch && day.attendance_status !== "CONFIG_ERROR" && !day.is_pending_approval
                      ? "—"
                      : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <PunchEntryDialog
        open={punchOpen}
        onOpenChange={setPunchOpen}
        employeeId={employeeId}
        employeeLabel={employeeLabel}
        onRecorded={onPunchRecorded}
      />
    </div>
  );
}
