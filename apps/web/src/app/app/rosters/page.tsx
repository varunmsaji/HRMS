"use client";

import { CalendarCheck, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmployeeIdentityCell } from "@/components/employee/employee-identity";
import { EmployeeSelect } from "@/components/employee/employee-select";
import { RosterEntryDialog } from "@/components/shift-roster/roster-entry-dialog";
import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { BusyRegion } from "@/components/common/busy-region";
import { PaginationControls } from "@/components/common/pagination-controls";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableToolbar,
} from "@/components/ui/table";
import { TableSkeleton } from "@/components/ui/skeleton";
import { isAbortError, useLatestRequest } from "@/hooks/use-latest-request";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import { useEmployeeNames } from "@/lib/employee/use-employee-names";
import { ROSTER_STATUSES, type RosterStatus, type ShiftRoster } from "@/lib/shift-roster/types";

interface ShiftOption {
  id: string;
  name: string;
  code: string | null;
}

function shiftDisplayName(shift: ShiftOption | undefined, shiftId: string): string {
  if (!shift) return shiftId;
  return shift.code ? `${shift.name} (${shift.code})` : shift.name;
}

function dayLabel(roster: ShiftRoster, shifts: Map<string, ShiftOption>): string {
  if (roster.is_week_off_override) return "Week off";
  if (roster.is_holiday_working_override) {
    return roster.shift_id
      ? `Working holiday · ${shiftDisplayName(shifts.get(roster.shift_id), roster.shift_id)}`
      : "Working holiday";
  }
  return roster.shift_id ? shiftDisplayName(shifts.get(roster.shift_id), roster.shift_id) : "—";
}

function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** `/v1/rosters` list/filter + create (architecture §4.2/§9.7/§25, WD-27). Every roster row here
 * is already DataScope-filtered server-side, mirroring the Attendance dashboard's own posture. */
export default function RostersPage() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const { toast } = useToast();
  const canManage = can("ATTENDANCE.ROSTER_MANAGE");

  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [dateFrom, setDateFrom] = useState(today);
  const [dateTo, setDateTo] = useState(addDays(today, 13));
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<RosterStatus | "">("");

  const [rosters, setRosters] = useState<ShiftRoster[] | null>(null);
  const directory = useEmployeeDirectory();
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const beginRequest = useLatestRequest();
  const [shifts, setShifts] = useState<ShiftOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ShiftRoster | null>(null);

  const rosterEmployeeIds = useMemo(() => (rosters ?? []).map((r) => r.employee_id), [rosters]);
  const employeeName = useEmployeeNames(rosterEmployeeIds, directory.employees);

  const shiftById = useMemo(() => {
    const map = new Map<string, ShiftOption>();
    for (const shift of shifts) map.set(shift.id, shift);
    return map;
  }, [shifts]);

  const load = useCallback(async () => {
    const request = beginRequest();
    setLoading(true);
    setError(null);
    try {
      const { data, pagination: meta } = await apiClient.getList<ShiftRoster>(
        "/rosters",
        {
          page,
          per_page: 100,
          date_from: dateFrom,
          date_to: dateTo,
          employee_id: employeeFilter || undefined,
          status: statusFilter || undefined,
        },
        { signal: request.signal },
      );
      if (!request.isCurrent()) return;
      setRosters(data);
      setPagination(meta);
    } catch (err) {
      if (isAbortError(err) || !request.isCurrent()) return;
      setRosters(null);
      setPagination(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      if (request.isCurrent()) setLoading(false);
    }
  }, [beginRequest, page, dateFrom, dateTo, employeeFilter, statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void apiClient
      .get<ShiftOption[]>("/shifts")
      .then(setShifts)
      .catch(() => setShifts([]));
  }, []);

  function openCreate() {
    setEditing(null);
    setDialogOpen(true);
  }

  function openEdit(roster: ShiftRoster) {
    setEditing(roster);
    setDialogOpen(true);
  }

  function onSaved(_roster: ShiftRoster) {
    void load();
  }

  async function handlePublish(roster: ShiftRoster) {
    try {
      await apiClient.post<ShiftRoster>(
        `/rosters/${roster.id}/publish`,
        {},
        { ifMatch: String(roster.version) },
      );
      toast({ title: "Roster entry published", variant: "success" });
      await load();
    } catch (err) {
      toast({ title: "Could not publish", description: describeApiError(err), variant: "danger" });
    }
  }

  async function handleDelete(roster: ShiftRoster) {
    try {
      await apiClient.delete<ShiftRoster>(`/rosters/${roster.id}`, {
        ifMatch: String(roster.version),
      });
      toast({ title: "Roster entry removed", variant: "success" });
      await load();
    } catch (err) {
      toast({ title: "Could not remove", description: describeApiError(err), variant: "danger" });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Shift Rosters"
        description="Per-employee, per-date schedule overrides — outrank the default assignment shift for attendance."
        actions={
          canManage ? (
            <div className="flex gap-2">
              <Button type="button" variant="outline" asChild>
                <Link href="/app/rosters/grid">Team grid</Link>
              </Button>
              <Button type="button" variant="outline" asChild>
                <Link href="/app/rosters/calendar">Calendar view</Link>
              </Button>
              <Button type="button" onClick={openCreate}>
                <Plus className="h-4 w-4" aria-hidden="true" />
                Add roster entry
              </Button>
            </div>
          ) : (
            <Button type="button" variant="outline" asChild>
              <Link href="/app/rosters/calendar">Calendar view</Link>
            </Button>
          )
        }
      />

      <TableContainer>
        <TableToolbar className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <FormField id="rosters-date-from" label="From">
            <Input
              type="date"
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value);
                setPage(1);
              }}
            />
          </FormField>
          <FormField id="rosters-date-to" label="To">
            <Input
              type="date"
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value);
                setPage(1);
              }}
            />
          </FormField>
          <FormField id="rosters-employee" label="Employee">
            <EmployeeSelect
              id="rosters-employee-select"
              directory={directory}
              value={employeeFilter}
              emptyLabel="All employees"
              onChange={(id) => {
                setEmployeeFilter(id);
                setPage(1);
              }}
            />
          </FormField>
          <FormField id="rosters-status" label="Status">
            <NativeSelect
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value as RosterStatus | "");
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              {ROSTER_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </TableToolbar>

        {loading && rosters === null ? (
          <div role="status" aria-label="Loading roster entries">
            <TableSkeleton rows={8} columns={5} />
            <span className="sr-only">Loading roster entries…</span>
          </div>
        ) : null}
        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view rosters."
                  : error.message
              }
              onRetry={() => void load()}
            />
          </div>
        ) : null}
        {!error && rosters && rosters.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={CalendarCheck}
              title="No roster entries in this range."
              description="Add an entry to override an employee's default shift for a specific date."
              action={
                canManage ? (
                  <Button type="button" onClick={openCreate}>
                    Add roster entry
                  </Button>
                ) : undefined
              }
            />
          </div>
        ) : null}
        {!error && rosters && rosters.length > 0 ? (
          <BusyRegion busy={loading} label="Refreshing roster entries…">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Date</TableHead>
                <TableHead>Employee</TableHead>
                <TableHead>Day</TableHead>
                <TableHead>Status</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rosters.map((roster) => {
                return (
                  <TableRow key={roster.id}>
                    <TableCell className="tabular-nums text-foreground-secondary">
                      <CompanyDate value={roster.roster_date} />
                    </TableCell>
                    <TableCell>
                      <EmployeeIdentityCell
                        name={employeeName(roster.employee_id)}
                        size="sm"
                      />
                    </TableCell>
                    <TableCell className="text-foreground-secondary">
                      {dayLabel(roster, shiftById)}
                    </TableCell>
                    <TableCell>
                      <Badge variant={roster.status === "PUBLISHED" ? "success" : "outline"} dot>
                        {roster.status}
                      </Badge>
                    </TableCell>
                    <TableCell align="right">
                      <div className="flex justify-end gap-2">
                        {canManage && roster.status === "DRAFT" ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="xs"
                            onClick={() => void handlePublish(roster)}
                          >
                            Publish
                          </Button>
                        ) : null}
                        {canManage ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="xs"
                            onClick={() => openEdit(roster)}
                          >
                            Edit
                          </Button>
                        ) : null}
                        {canManage ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="xs"
                            onClick={() => void handleDelete(roster)}
                          >
                            Remove
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          </BusyRegion>
        ) : null}
        {!error && pagination ? (
          <PaginationControls pagination={pagination} onPageChange={setPage} disabled={loading} />
        ) : null}
      </TableContainer>

      <RosterEntryDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        roster={editing}
        onSaved={onSaved}
      />
    </div>
  );
}
