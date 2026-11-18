"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AttendanceStatusBadge } from "@/components/attendance/attendance-status-badge";
import {
  DailyHoursChart,
  StatusBreakdown,
} from "@/components/attendance/employee-insights-charts";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { apiClient } from "@/lib/api/client";
import {
  BUCKET_GLYPHS,
  BUCKET_LABELS,
  BUCKET_TONES,
} from "@/lib/attendance/dashboard";
import {
  dailyHours,
  formatCountdown,
  formatDayCount,
  monthRange,
  monthStats,
  monthWeeks,
  shiftMonth,
  statusBreakdown,
  todayStatus,
  type CalendarCell,
  type TodayState,
} from "@/lib/attendance/employee-analytics";
import {
  businessToday,
  formatClockTime,
  formatMinutes,
} from "@/lib/attendance/format";
import type { AttendanceDay, Punch } from "@/lib/attendance/types";
import { useAuth } from "@/lib/auth/auth-context";
import { cn } from "@/lib/utils";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

const STATE_COPY: Record<
  TodayState,
  { label: string; dot: string; tone: string }
> = {
  WORKING: { label: "Working", dot: "bg-success", tone: "text-success" },
  ON_BREAK: { label: "On a break", dot: "bg-warning", tone: "text-warning" },
  CHECKED_OUT: { label: "Checked out", dot: "bg-info", tone: "text-info" },
  NOT_STARTED: {
    label: "Shift not started",
    dot: "bg-border-strong",
    tone: "text-foreground-secondary",
  },
  NOT_CHECKED_IN: {
    label: "Not checked in yet",
    dot: "bg-warning",
    tone: "text-warning",
  },
  ON_LEAVE: { label: "On leave", dot: "bg-on-leave", tone: "text-on-leave" },
  HOLIDAY: { label: "Holiday", dot: "bg-holiday", tone: "text-holiday" },
  WEEKLY_OFF: { label: "Weekly off", dot: "bg-holiday", tone: "text-holiday" },
  NO_SHIFT: {
    label: "Nothing scheduled today",
    dot: "bg-border-strong",
    tone: "text-foreground-secondary",
  },
  NOT_EMPLOYED: {
    label: "Not employed on this date",
    dot: "bg-border",
    tone: "text-foreground-muted",
  },
  ABSENT: { label: "Absent", dot: "bg-danger", tone: "text-danger" },
};

function monthTitle(month: string): string {
  return new Date(`${month}-01T00:00:00Z`).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function Tile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-border-subtle bg-surface-secondary/60 px-4 py-3">
      <dt className="text-xs font-medium text-foreground-muted">{label}</dt>
      <dd
        className={cn(
          "mt-1 truncate text-xl font-semibold tabular-nums text-foreground",
          tone,
        )}
      >
        {value}
      </dd>
      {hint ? (
        <p className="mt-0.5 truncate text-xs text-foreground-muted">{hint}</p>
      ) : null}
    </div>
  );
}

function Fact({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-foreground-muted">{label}</dt>
      <dd className="mt-0.5 truncate text-sm font-semibold tabular-nums text-foreground">
        {children}
      </dd>
    </div>
  );
}

/** Today strip, month tiles and the month calendar for one employee, read from the attendance
 * days and punches the API already serves (so the figures match the attendance pages). The server
 * filters by the viewer's data scope; a caller without access sees a short message, not numbers. */
export function EmployeeInsights({
  employeeId,
  shiftName,
}: {
  employeeId: string;
  shiftName: string | null;
}) {
  const { user } = useAuth();
  const tz = user?.company_timezone ?? "Asia/Kolkata";
  const today = businessToday(tz);

  const [month, setMonth] = useState(today.slice(0, 7));
  const [days, setDays] = useState<AttendanceDay[] | null>(null);
  const [todayDay, setTodayDay] = useState<AttendanceDay | null>(null);
  const [punches, setPunches] = useState<Punch[] | null>(null);
  const [failed, setFailed] = useState<"denied" | "error" | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [selected, setSelected] = useState<string | null>(null);

  const fail = (err: unknown) => {
    const status = (err as { status?: number })?.status;
    setFailed(status === 403 ? "denied" : "error");
  };

  const loadToday = useCallback(async () => {
    try {
      const [dayRows, punchRows] = await Promise.all([
        apiClient.get<AttendanceDay[]>(
          `/attendance/days?employee_id=${employeeId}&date_from=${today}&date_to=${today}`,
        ),
        apiClient.get<Punch[]>(
          `/attendance/punches?employee_id=${employeeId}&date_from=${today}&date_to=${today}`,
        ),
      ]);
      setTodayDay(dayRows[0] ?? null);
      setPunches(punchRows);
    } catch (err) {
      fail(err);
    }
  }, [employeeId, today]);

  const loadMonth = useCallback(async () => {
    const { from, to } = monthRange(month);
    try {
      setDays(null);
      setDays(
        await apiClient.get<AttendanceDay[]>(
          `/attendance/days?employee_id=${employeeId}&date_from=${from}&date_to=${to}`,
        ),
      );
    } catch (err) {
      fail(err);
    }
  }, [employeeId, month]);

  useEffect(() => {
    void loadToday();
    // Keep the strip live: the clock moves every minute, the punches are re-read every two.
    const tick = setInterval(() => setNow(new Date()), 60_000);
    const refresh = setInterval(() => void loadToday(), 120_000);
    return () => {
      clearInterval(tick);
      clearInterval(refresh);
    };
  }, [loadToday]);

  useEffect(() => {
    void loadMonth();
    setSelected(null);
  }, [loadMonth]);

  const status = useMemo(
    () => (punches ? todayStatus(todayDay, punches, now) : null),
    [todayDay, punches, now],
  );
  const stats = useMemo(
    () => (days ? monthStats(days, today) : null),
    [days, today],
  );
  const hours = useMemo(() => dailyHours(days ?? [], today), [days, today]);
  const breakdown = useMemo(
    () => statusBreakdown(days ?? [], today),
    [days, today],
  );
  const weeks = useMemo(
    () => monthWeeks(month, days ?? [], today),
    [month, days, today],
  );
  const selectedCell = useMemo(
    () =>
      weeks
        .flat()
        .find((c): c is CalendarCell => c !== null && c.date === selected) ??
      null,
    [weeks, selected],
  );

  if (failed === "denied") return null;
  if (failed === "error") {
    return (
      <p
        role="alert"
        className="rounded-xl border border-border bg-surface p-4 text-sm text-foreground-muted"
      >
        Attendance figures could not be loaded right now.
      </p>
    );
  }

  const copy = status ? STATE_COPY[status.state] : null;
  const atCurrentMonth = month >= today.slice(0, 7);

  return (
    <div className="space-y-5">
      <section
        aria-label="Today"
        className="rounded-2xl border border-border bg-surface p-5 shadow-elevation-1"
      >
        {!status || !copy ? (
          <Skeleton className="h-16 w-full" />
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-4">
            <div className="flex items-center gap-3">
              <span className="relative flex h-3 w-3">
                {status.state === "WORKING" ? (
                  <span
                    className={cn(
                      "absolute inline-flex h-full w-full animate-ping rounded-full opacity-60",
                      copy.dot,
                    )}
                  />
                ) : null}
                <span
                  className={cn(
                    "relative inline-flex h-3 w-3 rounded-full",
                    copy.dot,
                  )}
                />
              </span>
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                  Today
                </p>
                <p
                  className={cn("text-lg font-semibold", copy.tone)}
                  data-testid="today-state"
                >
                  {copy.label}
                  {status.state === "HOLIDAY" && status.holidayName
                    ? ` · ${status.holidayName}`
                    : ""}
                </p>
                <p className="text-sm text-foreground-secondary">
                  {status.state === "WORKING" || status.state === "ON_BREAK"
                    ? `In since ${formatClockTime(status.firstIn, tz)}`
                    : status.state === "CHECKED_OUT"
                      ? `Left at ${formatClockTime(status.lastOut, tz)}`
                      : status.state === "NOT_STARTED" &&
                          status.minutesToShiftStart !== null
                        ? `Starts in ${formatCountdown(status.minutesToShiftStart)}`
                        : status.state === "NOT_CHECKED_IN"
                          ? `Shift began at ${formatClockTime(status.scheduledStart, tz)}`
                          : status.state === "NO_SHIFT" && !todayDay
                            ? "Today's attendance has not been calculated yet."
                            : " "}
                </p>
              </div>
            </div>
            <dl className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-4">
              <Fact label="Shift">
                {shiftName ?? "Not set"}
                {status.scheduledStart && status.scheduledEnd ? (
                  <span className="block text-xs font-normal text-foreground-muted">
                    {formatClockTime(status.scheduledStart, tz)}–
                    {formatClockTime(status.scheduledEnd, tz)}
                  </span>
                ) : null}
              </Fact>
              <Fact label="First in / last out">
                {status.firstIn ? formatClockTime(status.firstIn, tz) : "—"}
                {" / "}
                {status.state === "CHECKED_OUT" && status.lastOut
                  ? formatClockTime(status.lastOut, tz)
                  : "—"}
              </Fact>
              <Fact label="Worked today">
                {status.workedMinutes !== null
                  ? formatMinutes(status.workedMinutes)
                  : "—"}
              </Fact>
              <Fact label="Shift ends">
                {status.minutesToShiftEnd === null
                  ? "—"
                  : status.minutesToShiftEnd > 0
                    ? `in ${formatCountdown(status.minutesToShiftEnd)}`
                    : "Over"}
              </Fact>
            </dl>
          </div>
        )}
      </section>

      <section
        aria-label="Month attendance"
        className="rounded-2xl border border-border bg-surface p-5 shadow-elevation-1"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-foreground">
            {monthTitle(month)}
          </h2>
          <div className="flex items-center gap-1">
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-label="Previous month"
              onClick={() => setMonth(shiftMonth(month, -1))}
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={month === today.slice(0, 7)}
              onClick={() => setMonth(today.slice(0, 7))}
            >
              This month
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-label="Next month"
              disabled={atCurrentMonth}
              onClick={() => setMonth(shiftMonth(month, 1))}
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </div>

        {!stats ? (
          <Skeleton className="mt-4 h-40 w-full" />
        ) : (
          <>
            <dl className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
              <Tile
                label="Days worked"
                value={formatDayCount(stats.daysWorked)}
                hint={`of ${stats.expectedDays} working days`}
              />
              <Tile
                label="Absent"
                value={String(stats.absent)}
                tone={stats.absent > 0 ? "text-danger" : undefined}
                hint={
                  stats.leave > 0 ? `${stats.leave} on leave` : "No leave taken"
                }
              />
              <Tile
                label="Late arrivals"
                value={String(stats.lateDays)}
                hint={
                  stats.lateDays > 0
                    ? `${formatMinutes(stats.lateMinutes)} in total`
                    : "None"
                }
              />
              <Tile
                label="Punctuality"
                value={
                  stats.punctuality === null ? "—" : `${stats.punctuality}%`
                }
                hint="days on time"
              />
              <Tile
                label="Hours worked"
                value={formatMinutes(stats.workedMinutes)}
                hint={
                  stats.missingPunch > 0
                    ? `${stats.missingPunch} missing a punch`
                    : undefined
                }
              />
              <Tile
                label="Average a day"
                value={
                  stats.avgWorkedMinutes === null
                    ? "—"
                    : formatMinutes(stats.avgWorkedMinutes)
                }
              />
              <Tile
                label="Overtime"
                value={formatMinutes(stats.otApprovedMinutes)}
                hint={
                  stats.otDetectedMinutes > stats.otApprovedMinutes
                    ? `${formatMinutes(stats.otDetectedMinutes)} detected`
                    : "approved"
                }
              />
              <Tile
                label="Early exits"
                value={String(stats.earlyOutDays)}
                hint={
                  stats.earlyOutDays > 0
                    ? `${formatMinutes(stats.earlyOutMinutes)} in total`
                    : "None"
                }
              />
            </dl>

            <div className="mt-5 grid gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
              <div>
                <div className="grid grid-cols-7 gap-1 text-center text-xs font-medium text-foreground-muted">
                  {WEEKDAYS.map((w) => (
                    <span key={w}>{w}</span>
                  ))}
                </div>
                <div
                  role="grid"
                  aria-label={`Attendance for ${monthTitle(month)}`}
                  className="mt-1 space-y-1"
                >
                  {weeks.map((week, wi) => (
                    <div role="row" key={wi} className="grid grid-cols-7 gap-1">
                      {week.map((cell, ci) =>
                        cell === null ? (
                          <span key={ci} role="gridcell" aria-hidden="true" />
                        ) : (
                          <button
                            key={cell.date}
                            type="button"
                            role="gridcell"
                            aria-selected={selected === cell.date}
                            aria-label={`${cell.date}, ${cell.bucket ? BUCKET_LABELS[cell.bucket] : cell.isFuture ? "upcoming" : "no record"}`}
                            onClick={() =>
                              setSelected(
                                selected === cell.date ? null : cell.date,
                              )
                            }
                            className={cn(
                              "flex h-9 flex-col items-center justify-center rounded-md border border-transparent text-xs leading-tight transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                              cell.bucket && !cell.isFuture
                                ? BUCKET_TONES[cell.bucket].cell
                                : "bg-surface-secondary text-foreground-muted",
                              cell.isFuture && "opacity-50",
                              cell.isToday && "ring-2 ring-primary",
                              selected === cell.date && "border-foreground",
                            )}
                          >
                            <span className="font-medium tabular-nums">
                              {cell.dayOfMonth}
                            </span>
                            {cell.bucket && !cell.isFuture ? (
                              <span className="text-[9px] font-semibold">
                                {BUCKET_GLYPHS[cell.bucket]}
                              </span>
                            ) : null}
                          </button>
                        ),
                      )}
                    </div>
                  ))}
                </div>
                <ul
                  className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-foreground-secondary"
                  aria-label="Legend"
                >
                  {(
                    [
                      "PRESENT",
                      "REMOTE",
                      "HALF_DAY",
                      "ABSENT",
                      "LEAVE",
                      "HOLIDAY",
                      "WEEKLY_OFF",
                    ] as const
                  ).map((b) => (
                    <li key={b} className="inline-flex items-center gap-1.5">
                      <span
                        className={cn(
                          "inline-flex h-4 min-w-4 items-center justify-center rounded px-0.5 text-[9px] font-semibold",
                          BUCKET_TONES[b].cell,
                        )}
                      >
                        {BUCKET_GLYPHS[b]}
                      </span>
                      {BUCKET_LABELS[b]}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="space-y-6">
                <StatusBreakdown items={breakdown} />
                <DailyHoursChart
                  bars={hours.bars}
                  scheduledMinutes={hours.scheduledMinutes}
                />
              </div>
            </div>

            {selectedCell ? (
              <div
                className="mt-4 rounded-xl border border-border bg-surface-secondary/50 p-4"
                data-testid="day-detail"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-foreground">
                    {new Date(
                      `${selectedCell.date}T00:00:00Z`,
                    ).toLocaleDateString("en-US", {
                      weekday: "long",
                      day: "numeric",
                      month: "long",
                      timeZone: "UTC",
                    })}
                  </p>
                  {selectedCell.day ? (
                    <AttendanceStatusBadge
                      status={selectedCell.day.attendance_status}
                    />
                  ) : null}
                </div>
                {selectedCell.day ? (
                  <>
                    <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                      <Fact label="First in">
                        {formatClockTime(selectedCell.day.actual_first_in, tz)}
                      </Fact>
                      <Fact label="Last out">
                        {formatClockTime(selectedCell.day.actual_last_out, tz)}
                      </Fact>
                      <Fact label="Worked">
                        {formatMinutes(selectedCell.day.worked_minutes)}
                      </Fact>
                      <Fact label="Late / early out">
                        {selectedCell.day.is_late
                          ? formatMinutes(selectedCell.day.late_minutes)
                          : "—"}
                        {" / "}
                        {selectedCell.day.is_early_out
                          ? formatMinutes(
                              selectedCell.day.early_departure_minutes,
                            )
                          : "—"}
                      </Fact>
                    </dl>
                    {selectedCell.day.holiday_name ? (
                      <p className="mt-2 text-sm text-foreground-secondary">
                        {selectedCell.day.holiday_name}
                      </p>
                    ) : null}
                    <Link
                      href={`/app/attendance/${selectedCell.day.id}`}
                      className="mt-3 inline-block text-sm font-medium text-primary hover:underline"
                    >
                      Open the full day
                    </Link>
                  </>
                ) : (
                  <p className="mt-2 text-sm text-foreground-muted">
                    {selectedCell.isFuture
                      ? "This day has not happened yet."
                      : "No attendance record for this day."}
                  </p>
                )}
              </div>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}
