"use client";

import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { CalendarGrid } from "@/components/attendance/hr-calendar/calendar-grid";
import { DetailDrawer, type Selection } from "@/components/attendance/hr-calendar/detail-drawer";
import { useSection } from "@/components/attendance/dashboard/use-dashboard-data";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api/client";
import type { EmployeeLite } from "@/lib/attendance/dashboard";
import { businessToday } from "@/lib/attendance/format";
import { HR_CALENDAR_PERMISSIONS, buildHrCalendar, filterRows, monthDates, shiftMonth } from "@/lib/attendance/hr-calendar";
import type { AttendanceDay } from "@/lib/attendance/types";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";

const PAGE_SIZE = 100;
const MAX_PAGES = 5;

async function loadEmployees(): Promise<{ items: EmployeeLite[]; total: number }> {
  const first = await apiClient.getList<EmployeeLite>("/employees", { page: 1, per_page: PAGE_SIZE });
  const items = [...first.data];
  const last = Math.min(first.pagination?.total_pages ?? 1, MAX_PAGES);
  if (last > 1) {
    const rest = await Promise.all(
      Array.from({ length: last - 1 }, (_, i) =>
        apiClient.getList<EmployeeLite>("/employees", { page: i + 2, per_page: PAGE_SIZE }),
      ),
    );
    for (const p of rest) items.push(...p.data);
  }
  return { items, total: first.pagination?.total ?? items.length };
}

const DAYS_PER_PAGE = 500;
/** Safety bound: 20 pages is 10,000 day rows (about 320 people for a month). Beyond that the page says so. */
const MAX_DAY_PAGES = 20;

/** Every attendance day in the range. The endpoint returns at most 500 rows a page, so a month for
 * a whole company spans several pages; the first tells us how many, the rest load in parallel. */
async function loadDays(from: string, to: string): Promise<{ items: AttendanceDay[]; total: number }> {
  const q = { date_from: from, date_to: to, per_page: DAYS_PER_PAGE };
  const first = await apiClient.getList<AttendanceDay>("/attendance/days", { ...q, page: 1 });
  const items = [...first.data];
  const last = Math.min(first.pagination?.total_pages ?? 1, MAX_DAY_PAGES);
  if (last > 1) {
    const rest = await Promise.all(
      Array.from({ length: last - 1 }, (_, i) =>
        apiClient.getList<AttendanceDay>("/attendance/days", { ...q, page: i + 2 }),
      ),
    );
    for (const p of rest) items.push(...p.data);
  }
  return { items, total: first.pagination?.total ?? items.length };
}

/** HR view: every employee's attendance for a month as one calendar. */
export default function AttendanceCalendarPage() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [month, setMonth] = useState(today.slice(0, 7));
  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<Selection>(null);
  const allowed = HR_CALENDAR_PERMISSIONS.every((code) => can(code));

  const dates = useMemo(() => monthDates(month), [month]);
  const days = useSection(() => loadDays(dates[0], dates[dates.length - 1]), `cal|${month}`, allowed);
  const employees = useSection(loadEmployees, "cal-employees", allowed);

  const rows = useMemo(
    () => (days.data && employees.data ? buildHrCalendar(days.data.items, employees.data.items, dates) : null),
    [days.data, employees.data, dates],
  );
  const visible = rows ? filterRows(rows, query) : null;
  const truncated = employees.data ? employees.data.total > employees.data.items.length : false;
  const daysTruncated = days.data ? days.data.total > days.data.items.length : false;
  const monthLabel = new Date(`${month}-01T00:00:00Z`).toLocaleDateString("en-GB", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Attendance calendar"
        description="Every employee's attendance for the month in one view. Click a box for that day's details, or a name for their whole month."
        actions={
          <Button asChild variant="outline">
            <Link href="/app/attendance">Back to attendance</Link>
          </Button>
        }
      />

      {!allowed ? (
        <ErrorState message="The attendance calendar is available to people who can view everyone's attendance and the employee directory." />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface p-1">
              <Button type="button" variant="ghost" size="icon" className="h-8 w-8" aria-label="Previous month" onClick={() => setMonth(shiftMonth(month, -1))}>
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              </Button>
              <span className="min-w-36 px-2 text-center text-sm font-semibold text-foreground">{monthLabel}</span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                aria-label="Next month"
                disabled={month >= today.slice(0, 7)}
                onClick={() => setMonth(shiftMonth(month, 1))}
              >
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </Button>
              {month !== today.slice(0, 7) ? (
                <Button type="button" variant="outline" size="sm" onClick={() => setMonth(today.slice(0, 7))}>
                  This month
                </Button>
              ) : null}
            </div>
            <div className="relative w-full max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-foreground-muted" aria-hidden="true" />
              <Input
                type="search"
                aria-label="Search employees"
                placeholder="Search name or code…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="pl-8"
              />
            </div>
          </div>

          {truncated ? (
            <p role="note" className="text-xs text-foreground-muted">
              Showing the first {employees.data?.items.length} of {employees.data?.total} employees.
            </p>
          ) : null}

          {daysTruncated ? (
            <p role="alert" className="rounded-md border border-warning-border bg-warning-subtle px-3 py-2 text-sm">
              This month has more attendance records than could be loaded ({days.data?.items.length.toLocaleString()} of{" "}
              {days.data?.total.toLocaleString()}), so some boxes may be missing.
            </p>
          ) : null}

          {days.status === "error" || employees.status === "error" ? (
            <ErrorState
              message={
                (days.error ?? employees.error)?.status === 403
                  ? "You do not have permission to view attendance for everyone."
                  : "The calendar couldn't be loaded. Please try again."
              }
              onRetry={() => {
                days.retry();
                employees.retry();
              }}
            />
          ) : !visible ? (
            <LoadingState label="Loading the calendar…" />
          ) : visible.length === 0 ? (
            <p className="py-10 text-center text-sm text-foreground-muted">No employees match.</p>
          ) : (
            <CalendarGrid
              rows={visible}
              dates={dates}
              today={today}
              onPickDay={(row, day) => setSelection({ row, day })}
              onPickEmployee={(row) => setSelection({ row, day: null })}
            />
          )}
        </>
      )}

      <DetailDrawer selection={selection} month={month} onClose={() => setSelection(null)} />
    </div>
  );
}
