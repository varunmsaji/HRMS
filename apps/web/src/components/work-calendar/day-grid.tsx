"use client";

import type { DayType } from "@/lib/work-calendar/types";

const WEEKDAY_HEADERS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export type DayPresentation = {
  key: string;
  glyph: string;
  label: string;
  detail: string | null;
  className: string;
};

/** Derives how one resolver result is shown. Never decides what kind of day it is: it only
 * reads the fields the server already classified. A named optional/restricted holiday on a
 * `WORKING` day is shown as working, matching the resolver (PD-CAL-1). */
export function presentDay(day: DayType): DayPresentation {
  if (day.day_type === "SHUTDOWN") {
    return {
      key: "SHUTDOWN",
      glyph: "✕",
      label: "Shutdown",
      detail: day.holiday_name,
      className: "border-danger-border bg-danger-subtle text-danger",
    };
  }
  if (day.day_type === "HOLIDAY") {
    return {
      key: "HOLIDAY",
      glyph: "★",
      label: "Holiday",
      detail: day.holiday_name,
      className: "border-primary-border bg-primary-subtle text-primary",
    };
  }
  if (day.day_type === "WEEKLY_OFF") {
    const half = day.weekly_off_fraction !== null && Number(day.weekly_off_fraction) < 1;
    return {
      key: "WEEKLY_OFF",
      glyph: "○",
      label: half ? "Half-day weekly off" : "Weekly off",
      detail: day.holiday_on_weekly_off ? `${day.holiday_name ?? "Holiday"} (on weekly off)` : null,
      className: "border-border bg-surface-secondary text-foreground-secondary",
    };
  }
  if (day.day_type === "SPECIAL_WORKING") {
    return {
      key: "SPECIAL_WORKING",
      glyph: "◆",
      label: "Special working day",
      detail: day.holiday_name,
      className: "border-warning-border bg-warning-subtle text-warning",
    };
  }
  const named = day.optional_holiday_name ?? day.restricted_holiday_name ?? day.holiday_name;
  if (day.optional_holiday_name) {
    return {
      key: "WORKING_OPTIONAL",
      glyph: "·",
      label: "Working",
      detail: `Optional holiday: ${named} (still a working day)`,
      className: "border-border bg-surface text-foreground",
    };
  }
  if (day.restricted_holiday_name) {
    return {
      key: "WORKING_RESTRICTED",
      glyph: "·",
      label: "Working",
      detail: `Restricted holiday: ${named} (still a working day)`,
      className: "border-border bg-surface text-foreground",
    };
  }
  if (day.is_holiday_named) {
    return {
      key: "WORKING_HOLIDAY",
      glyph: "·",
      label: "Working",
      detail: `${named} (working holiday)`,
      className: "border-border bg-surface text-foreground",
    };
  }
  return {
    key: "WORKING",
    glyph: "·",
    label: "Working",
    detail: null,
    className: "border-border bg-surface text-foreground",
  };
}

export const LEGEND: Array<{ glyph: string; label: string; className: string }> = [
  { glyph: "·", label: "Working day", className: "border-border bg-surface text-foreground" },
  { glyph: "○", label: "Weekly off", className: "border-border bg-surface-secondary text-foreground-secondary" },
  { glyph: "★", label: "Holiday (non-working)", className: "border-primary-border bg-primary-subtle text-primary" },
  { glyph: "◆", label: "Special working day", className: "border-warning-border bg-warning-subtle text-warning" },
  { glyph: "✕", label: "Shutdown", className: "border-danger-border bg-danger-subtle text-danger" },
];

function parseIso(value: string): Date {
  const [y, m, d] = value.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function toIso(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** Monday-first weeks covering `[first, last]`; cells outside the supplied data stay blank. */
export function DayGrid({
  days,
  highlightMonth,
}: {
  days: DayType[];
  /** 0-11; days from other months are dimmed. */
  highlightMonth?: number;
}) {
  if (days.length === 0) return null;
  const byDate = new Map(days.map((d) => [d.date, d]));
  const first = parseIso(days[0].date);
  const last = parseIso(days[days.length - 1].date);
  const startOffset = (first.getUTCDay() + 6) % 7; // Monday=0
  const gridStart = new Date(first.getTime() - startOffset * 86_400_000);
  const endOffset = 6 - ((last.getUTCDay() + 6) % 7);
  const gridEnd = new Date(last.getTime() + endOffset * 86_400_000);

  const cells: string[] = [];
  for (let t = gridStart.getTime(); t <= gridEnd.getTime(); t += 86_400_000) {
    cells.push(toIso(new Date(t)));
  }

  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[44rem] grid-cols-7 gap-1.5" role="grid" aria-label="Calendar days">
        {WEEKDAY_HEADERS.map((name) => (
          <div
            key={name}
            role="columnheader"
            className="px-2 py-1 text-2xs font-semibold uppercase tracking-wider text-foreground-muted"
          >
            {name}
          </div>
        ))}
        {cells.map((iso) => {
          const day = byDate.get(iso);
          const dayNumber = Number(iso.slice(8, 10));
          if (!day) {
            return (
              <div
                key={iso}
                role="gridcell"
                aria-label={`${iso}: not loaded`}
                className="min-h-20 rounded-md border border-dashed border-border/60 bg-surface-secondary/30 p-2 text-xs tabular-nums text-foreground-disabled"
              >
                {dayNumber}
              </div>
            );
          }
          const view = presentDay(day);
          const dimmed =
            highlightMonth !== undefined && parseIso(iso).getUTCMonth() !== highlightMonth;
          return (
            <div
              key={iso}
              role="gridcell"
              data-day-kind={view.key}
              aria-label={`${iso}: ${view.label}${view.detail ? `, ${view.detail}` : ""}`}
              className={`min-h-20 rounded-md border p-2 text-xs transition-colors ${view.className} ${
                dimmed ? "opacity-45" : ""
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold tabular-nums text-foreground">{dayNumber}</span>
                <span aria-hidden="true" className="text-xs font-bold">
                  {view.glyph}
                </span>
              </div>
              <p className="mt-1 font-medium text-foreground">{view.label}</p>
              {view.detail ? (
                <p className="mt-0.5 break-words text-[11px] leading-snug text-foreground-secondary">
                  {view.detail}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function DayGridLegend() {
  return (
    <ul className="flex flex-wrap gap-3 text-xs text-foreground-secondary" aria-label="Legend">
      {LEGEND.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className={`inline-flex h-5 w-5 items-center justify-center rounded-sm border text-xs font-semibold ${item.className}`}
          >
            {item.glyph}
          </span>
          <span>{item.label}</span>
        </li>
      ))}
    </ul>
  );
}
