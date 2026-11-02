"use client";

import { presentDay } from "@/components/work-calendar/day-grid";
import { formatLongDate, formatMonthLabel, monthKeyOf, weeksBetween } from "@/lib/employee-calendar/month";
import type { EmployeeCalendar, EmployeeCalendarDay, EmployeeCalendarLeave } from "@/lib/employee-calendar/types";
import type { DayType } from "@/lib/work-calendar/types";

const WEEKDAYS = [
  { short: "Mon", full: "Monday" },
  { short: "Tue", full: "Tuesday" },
  { short: "Wed", full: "Wednesday" },
  { short: "Thu", full: "Thursday" },
  { short: "Fri", full: "Friday" },
  { short: "Sat", full: "Saturday" },
  { short: "Sun", full: "Sunday" },
];

/** The classifier output the admin calendar screens already render; `presentDay` is reused so
 * the employee view never decides what kind of day it is, it only labels what the server said. */
function toDayType(day: EmployeeCalendarDay): DayType | null {
  if (!day.configured || day.day_type === null) return null;
  return {
    date: day.date,
    day_type: day.day_type,
    holiday_name: day.holiday_name,
    exception_type: day.exception_type,
    holiday_on_weekly_off: day.holiday_on_weekly_off,
    is_holiday_named: day.is_holiday_named,
    optional_holiday_name: day.optional_holiday_name,
    restricted_holiday_name: day.restricted_holiday_name,
    weekly_off_fraction: day.weekly_off_fraction,
    holiday_type: day.holiday_type,
    holiday_is_paid: null,
  };
}

export interface LeavePresentation {
  glyph: string;
  label: string;
  className: string;
}

/** Approved and pending leave differ by text, glyph and border style, never colour alone. */
export function presentLeave(leave: EmployeeCalendarLeave): LeavePresentation {
  const half =
    leave.half === "FIRST_HALF"
      ? " (first half)"
      : leave.half === "SECOND_HALF"
        ? " (second half)"
        : Number(leave.fraction) < 1
          ? " (half day)"
          : "";
  if (leave.status === "APPROVED") {
    return {
      glyph: "✓",
      label: `Approved leave${half}`,
      className: "border border-solid border-success/60 bg-success/10",
    };
  }
  return {
    glyph: "?",
    label: `Pending leave${half}`,
    className: "border border-dashed border-warning bg-warning/10",
  };
}

export const EMPLOYEE_LEGEND: Array<{ glyph: string; label: string; className: string }> = [
  { glyph: "·", label: "Working day", className: "border border-border bg-background" },
  { glyph: "○", label: "Weekly off", className: "border border-border bg-accent" },
  { glyph: "★", label: "Holiday (non-working)", className: "border border-primary/40 bg-primary/10" },
  { glyph: "◆", label: "Special working day", className: "border border-warning/40 bg-warning/10" },
  { glyph: "✕", label: "Shutdown", className: "border border-danger/40 bg-danger/10" },
  { glyph: "✓", label: "Approved leave", className: "border border-solid border-success/60 bg-success/10" },
  { glyph: "?", label: "Pending leave (awaiting approval)", className: "border border-dashed border-warning bg-warning/10" },
];

export function EmployeeCalendarLegend() {
  return (
    <ul className="flex flex-wrap gap-3 text-xs text-foreground-muted" aria-label="Legend">
      {EMPLOYEE_LEGEND.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className={`inline-flex h-5 w-5 items-center justify-center rounded ${item.className}`}
          >
            {item.glyph}
          </span>
          {item.label}
        </li>
      ))}
    </ul>
  );
}

function DayCell({ day, inMonth, isToday }: { day: EmployeeCalendarDay; inMonth: boolean; isToday: boolean }) {
  const classified = toDayType(day);
  const view = classified ? presentDay(classified) : null;
  const dayNumber = Number(day.date.slice(8, 10));
  const leave = day.leave.map(presentLeave);
  const spoken = [
    formatLongDate(day.date),
    view ? view.label : "Calendar not set up",
    view?.detail ?? null,
    ...leave.map((item) => item.label),
    isToday ? "today" : null,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <td
      data-date={day.date}
      data-day-kind={view?.key ?? "UNCONFIGURED"}
      aria-current={isToday ? "date" : undefined}
      className={`h-24 min-w-[5.5rem] rounded-md border align-top p-1 text-xs ${
        view ? view.className : "border-dashed border-border bg-background"
      } ${inMonth ? "" : "opacity-50"} ${isToday ? "ring-2 ring-primary" : ""}`}
    >
      <span className="sr-only">{spoken}</span>
      <div aria-hidden="true">
        <div className="flex items-center justify-between">
          <span className="font-medium text-foreground">{dayNumber}</span>
          <span>{view ? view.glyph : "–"}</span>
        </div>
        <p className="mt-1 text-foreground">{view ? view.label : "Not set up"}</p>
        {view?.detail ? <p className="mt-0.5 break-words text-foreground-muted">{view.detail}</p> : null}
        {isToday ? <p className="mt-0.5 font-medium text-primary">Today</p> : null}
        {leave.map((item) => (
          <p key={item.label} className={`mt-1 rounded px-1 py-0.5 text-foreground ${item.className}`}>
            <span>{item.glyph}</span> {item.label}
          </p>
        ))}
      </div>
    </td>
  );
}

/** Read-only month grid. A real `<table>` keeps row/column semantics for screen readers without
 * needing roving-focus key handling, since nothing in it is interactive. */
export function EmployeeCalendarMonth({
  calendar,
  month,
  today,
}: {
  calendar: EmployeeCalendar;
  month: string;
  today: string;
}) {
  const byDate = new Map(calendar.days.map((d) => [d.date, d]));
  const weeks = weeksBetween(calendar.from_date, calendar.to_date);

  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[42rem] table-fixed border-separate border-spacing-1">
        <caption className="sr-only">Work calendar for {formatMonthLabel(month)}</caption>
        <thead>
          <tr>
            {WEEKDAYS.map((weekday) => (
              <th
                key={weekday.short}
                scope="col"
                abbr={weekday.full}
                className="px-1 pb-1 text-left text-xs font-medium uppercase tracking-wide text-foreground-muted"
              >
                {weekday.short}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((week) => (
            <tr key={week[0]}>
              {week.map((iso) => {
                const day = byDate.get(iso);
                return day ? (
                  <DayCell key={iso} day={day} inMonth={monthKeyOf(iso) === month} isToday={iso === today} />
                ) : (
                  <td key={iso} className="h-24 rounded-md border border-dashed border-border/50" />
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Counts shown above the grid, so the month can be read without scanning every cell. */
export function summariseMonth(calendar: EmployeeCalendar, month: string) {
  const inMonth = calendar.days.filter((d) => monthKeyOf(d.date) === month);
  const count = (pred: (d: EmployeeCalendarDay) => boolean) => inMonth.filter(pred).length;
  const nonWorking = (d: EmployeeCalendarDay) =>
    d.day_type === "WEEKLY_OFF" || d.day_type === "HOLIDAY" || d.day_type === "SHUTDOWN";
  return {
    working: count((d) => d.configured && !nonWorking(d)),
    nonWorking: count(nonWorking),
    approvedLeaveDays: count((d) => d.leave.some((l) => l.status === "APPROVED")),
    pendingLeaveDays: count((d) => d.leave.some((l) => l.status === "PENDING")),
  };
}
