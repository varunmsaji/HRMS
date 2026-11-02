"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmployeeSelect } from "@/components/employee/employee-select";
import { RosterEntryDialog } from "@/components/shift-roster/roster-entry-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { RosterTabs } from "@/components/shift-roster/roster-tabs";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { isAbortError, useLatestRequest } from "@/hooks/use-latest-request";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import { employeeOptionName, useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import type { ShiftRoster } from "@/lib/shift-roster/types";
import { cn } from "@/lib/utils";

interface ShiftOption {
  id: string;
  name: string;
  code: string | null;
}

function shiftLabel(shift: ShiftOption | undefined): string {
  if (!shift) return "";
  return shift.code ? `${shift.name} (${shift.code})` : shift.name;
}

function toIsoDate(year: number, monthIndex: number, day: number): string {
  return `${year}-${String(monthIndex + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Builds a 6-row x 7-col month grid (leading/trailing days from neighbouring months included
 * as null so every week row is a full 7 cells), matching a conventional month calendar layout. */
function buildMonthGrid(year: number, monthIndex: number): Array<{ iso: string; inMonth: boolean }[]> {
  const firstOfMonth = new Date(Date.UTC(year, monthIndex, 1));
  const daysInMonth = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
  const startWeekday = firstOfMonth.getUTCDay();

  const cells: { iso: string; inMonth: boolean }[] = [];
  for (let i = 0; i < startWeekday; i++) {
    const prevMonthDay = new Date(Date.UTC(year, monthIndex, 1 - (startWeekday - i)));
    cells.push({
      iso: prevMonthDay.toISOString().slice(0, 10),
      inMonth: false,
    });
  }
  for (let day = 1; day <= daysInMonth; day++) {
    cells.push({ iso: toIsoDate(year, monthIndex, day), inMonth: true });
  }
  while (cells.length % 7 !== 0 || cells.length < 35) {
    const last = new Date(`${cells[cells.length - 1]!.iso}T00:00:00Z`);
    last.setUTCDate(last.getUTCDate() + 1);
    cells.push({ iso: last.toISOString().slice(0, 10), inMonth: false });
  }

  const weeks: Array<{ iso: string; inMonth: boolean }[]> = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

/** Month view of one employee's `ShiftRoster` (architecture §26.2's "Roster Calendar", W5).
 * Click a day to add or edit its roster entry; DRAFT entries are visually distinct (dashed
 * border) from PUBLISHED ones since only the latter affect a live attendance calculation
 * (WD-27). */
export default function RosterCalendarPage() {
  const { can } = usePermissions();
  const { toast } = useToast();
  const canManage = can("ATTENDANCE.ROSTER_MANAGE");

  const today = useMemo(() => new Date(), []);
  const [year, setYear] = useState(today.getUTCFullYear());
  const [monthIndex, setMonthIndex] = useState(today.getUTCMonth());
  const [employeeId, setEmployeeId] = useState("");

  const directory = useEmployeeDirectory();
  const beginRequest = useLatestRequest();
  const [shifts, setShifts] = useState<ShiftOption[]>([]);
  const [rosters, setRosters] = useState<ShiftRoster[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [publishingAll, setPublishingAll] = useState(false);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogDate, setDialogDate] = useState<string | null>(null);
  const [dialogRoster, setDialogRoster] = useState<ShiftRoster | null>(null);

  const weeks = useMemo(() => buildMonthGrid(year, monthIndex), [year, monthIndex]);
  const monthLabel = useMemo(
    () => new Date(Date.UTC(year, monthIndex, 1)).toLocaleDateString(undefined, {
      month: "long",
      year: "numeric",
      timeZone: "UTC",
    }),
    [year, monthIndex],
  );

  const shiftById = useMemo(() => {
    const map = new Map<string, ShiftOption>();
    for (const shift of shifts) map.set(shift.id, shift);
    return map;
  }, [shifts]);

  const rosterByDate = useMemo(() => {
    const map = new Map<string, ShiftRoster>();
    for (const roster of rosters ?? []) map.set(roster.roster_date, roster);
    return map;
  }, [rosters]);

  const load = useCallback(async () => {
    if (!employeeId) {
      beginRequest();
      setRosters(null);
      return;
    }
    const request = beginRequest();
    setLoading(true);
    setError(null);
    try {
      const monthStart = toIsoDate(year, monthIndex, 1);
      const monthEnd = weeks[weeks.length - 1]![6]!.iso;
      const params = new URLSearchParams({
        employee_id: employeeId,
        date_from: monthStart,
        date_to: monthEnd,
      });
      // One employee has at most one roster entry per date, so a 6-week window is at most 42
      // rows — always a single, complete page of the (500-row) bounded endpoint.
      const data = await apiClient.get<ShiftRoster[]>(`/rosters?${params.toString()}`, {
        signal: request.signal,
      });
      if (!request.isCurrent()) return;
      setRosters(data);
    } catch (err) {
      if (isAbortError(err) || !request.isCurrent()) return;
      setRosters(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      if (request.isCurrent()) setLoading(false);
    }
  }, [beginRequest, employeeId, year, monthIndex, weeks]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void apiClient
      .get<ShiftOption[]>("/shifts")
      .then(setShifts)
      .catch(() => setShifts([]));
  }, []);

  function goToMonth(delta: number) {
    const next = new Date(Date.UTC(year, monthIndex + delta, 1));
    setYear(next.getUTCFullYear());
    setMonthIndex(next.getUTCMonth());
  }

  function openCell(iso: string) {
    if (!canManage) return;
    setDialogDate(iso);
    setDialogRoster(rosterByDate.get(iso) ?? null);
    setDialogOpen(true);
  }

  function onSaved(_roster: ShiftRoster) {
    void load();
  }

  async function handlePublishAllDrafts() {
    const drafts = (rosters ?? []).filter((r) => r.status === "DRAFT");
    if (drafts.length === 0) return;
    setPublishingAll(true);
    try {
      for (const draft of drafts) {
        await apiClient.post<ShiftRoster>(
          `/rosters/${draft.id}/publish`,
          {},
          { ifMatch: String(draft.version) },
        );
      }
      toast({ title: `Published ${drafts.length} roster entr${drafts.length === 1 ? "y" : "ies"}`, variant: "success" });
      await load();
    } catch (err) {
      toast({
        title: "Could not publish all entries",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setPublishingAll(false);
    }
  }

  const draftCount = (rosters ?? []).filter((r) => r.status === "DRAFT").length;
  const selectedEmployee = directory.employees.find((e) => e.id === employeeId);

  return (
    <div className="space-y-6">
      <RosterTabs active="calendar" />
      <PageHeader
        title="Roster Calendar"
        description="Month view of one employee's shift roster."
        actions={
          <Button type="button" variant="outline" asChild>
            <Link href="/app/rosters">List view</Link>
          </Button>
        }
      />

      <Card>
        <CardContent className="flex flex-col gap-4 pt-6 sm:flex-row sm:items-end sm:justify-between">
          <FormField id="roster-calendar-employee" label="Employee" className="sm:max-w-xs">
            <EmployeeSelect
              id="roster-calendar-employee-select"
              directory={directory}
              value={employeeId}
              emptyLabel="Choose an employee…"
              onChange={setEmployeeId}
            />
          </FormField>

          <div className="flex items-center gap-3">
            <Button type="button" variant="outline" size="icon" onClick={() => goToMonth(-1)}>
              <ChevronLeft className="h-4 w-4" />
              <span className="sr-only">Previous month</span>
            </Button>
            <p className="min-w-40 text-center text-sm font-medium text-foreground">{monthLabel}</p>
            <Button type="button" variant="outline" size="icon" onClick={() => goToMonth(1)}>
              <ChevronRight className="h-4 w-4" />
              <span className="sr-only">Next month</span>
            </Button>
          </div>

          {canManage && employeeId && draftCount > 0 ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => void handlePublishAllDrafts()}
              disabled={publishingAll}
            >
              {publishingAll ? "Publishing…" : `Publish ${draftCount} draft${draftCount === 1 ? "" : "s"}`}
            </Button>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          {!employeeId ? (
            <EmptyState
              title="Choose an employee to see their roster calendar."
              description="Select someone from the dropdown above."
            />
          ) : null}

          {employeeId && loading ? <LoadingState label="Loading roster…" /> : null}

          {employeeId && error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this employee's roster."
                  : error.message
              }
              onRetry={() => void load()}
            />
          ) : null}

          {employeeId && !loading && !error ? (
            <div className="space-y-2">
              <div className="grid grid-cols-7 gap-px overflow-hidden rounded-md border border-border bg-border text-xs font-medium uppercase tracking-wide text-foreground-muted">
                {WEEKDAY_LABELS.map((label) => (
                  <div key={label} className="bg-surface-secondary px-2 py-1.5 text-center">
                    {label}
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-7 gap-px overflow-hidden rounded-md border border-border bg-border">
                {weeks.flatMap((week) =>
                  week.map((cell) => {
                    const roster = rosterByDate.get(cell.iso);
                    const dayNumber = Number(cell.iso.slice(8, 10));
                    return (
                      <button
                        key={cell.iso}
                        type="button"
                        onClick={() => openCell(cell.iso)}
                        disabled={!canManage}
                        className={cn(
                          "flex min-h-24 flex-col items-start gap-1 bg-surface p-2 text-left text-xs transition-colors",
                          cell.inMonth ? "text-foreground" : "text-foreground-muted/60",
                          canManage ? "hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" : "cursor-default",
                        )}
                      >
                        <span className="text-sm font-medium">{dayNumber}</span>
                        {roster ? (
                          <>
                            <Badge
                              variant={roster.status === "PUBLISHED" ? "success" : "outline"}
                              className={cn(roster.status === "DRAFT" && "border-dashed")}
                            >
                              {roster.is_week_off_override
                                ? "Week off"
                                : roster.is_holiday_working_override
                                  ? "Holiday working"
                                  : shiftLabel(roster.shift_id ? shiftById.get(roster.shift_id) : undefined) || "Shift"}
                            </Badge>
                            {roster.status === "DRAFT" ? (
                              <span className="text-[10px] text-foreground-muted">Draft</span>
                            ) : null}
                          </>
                        ) : null}
                      </button>
                    );
                  }),
                )}
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <RosterEntryDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        roster={dialogRoster}
        employeeId={employeeId}
        employeeLabel={selectedEmployee ? employeeOptionName(selectedEmployee) : undefined}
        rosterDate={dialogDate ?? undefined}
        onSaved={onSaved}
      />
    </div>
  );
}
