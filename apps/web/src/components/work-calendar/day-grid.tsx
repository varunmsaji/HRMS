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
      className: "border-danger/40 bg-danger/10",
    };
  }
  if (day.day_type === "HOLIDAY") {
    return {
      key: "HOLIDAY",
      glyph: "★",
      label: "Holiday",
      detail: day.holiday_name,
      className: "border-primary/40 bg-primary/10",
    };
  }
  if (day.day_type === "WEEKLY_OFF") {
    const half = day.weekly_off_fraction !== null && Number(day.weekly_off_fraction) < 1;
    return {
      key: "WEEKLY_OFF",
      glyph: "○",
      label: half ? "Half-day weekly off" : "Weekly off",
      detail: day.holiday_on_weekly_off ? `${day.holiday_name ?? "Holiday"} (on weekly off)` : null,
      className: "border-border bg-accent",
    };
  }
  if (day.day_type === "SPECIAL_WORKING") {
    return {
      key: "SPECIAL_WORKING",
      glyph: "◆",
      label: "Special working day",
      detail: day.holiday_name,
      className: "border-warning/40 bg-warning/10",
    };
  }
  const named = day.optional_holiday_name ?? day.restricted_holiday_name ?? day.holiday_name;
  if (day.optional_holiday_name) {
    return {
      key: "WORKING_OPTIONAL",
      glyph: "·",
      label: "Working",
      detail: `Optional holiday: ${named} (still a working day)`,
      className: "border-border bg-background",
    };
  }
  if (day.restricted_holiday_name) {
    return {
      key: "WORKING_RESTRICTED",
      glyph: "·",
      label: "Working",
      detail: `Restricted holiday: ${named} (still a working day)`,
      className: "border-border bg-background",
    };
  }
  if (day.is_holiday_named) {
    return {
      key: "WORKING_HOLIDAY",
      glyph: "·",
      label: "Working",
      detail: `${named} (working holiday)`,
      className: "border-border bg-background",
    };
  }
  return {
    key: "WORKING",
    glyph: "·",
    label: "Working",
    detail: null,
    className: "border-border bg-background",
  };
}

export const LEGEND: Array<{ glyph: string; label: string; className: string }> = [
  { glyph: "·", label: "Working day", className: "border-border bg-background" },
  { glyph: "○", label: "Weekly off", className: "border-border bg-accent" },
  { glyph: "★", label: "Holiday (non-working)", className: "border-primary/40 bg-primary/10" },
  { glyph: "◆", label: "Special working day", className: "border-warning/40 bg-warning/10" },
  { glyph: "✕", label: "Shutdown", className: "border-danger/40 bg-danger/10" },
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
      <div className="grid min-w-[42rem] grid-cols-7 gap-1" role="grid" aria-label="Calendar days">
        {WEEKDAY_HEADERS.map((name) => (
          <div
            key={name}
            role="columnheader"
            className="px-1 pb-1 text-xs font-medium uppercase tracking-wide text-foreground-muted"
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
                className="min-h-20 rounded-md border border-dashed border-border/50 p-1 text-xs text-foreground-muted/50"
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
              className={`min-h-20 rounded-md border p-1 text-xs ${view.className} ${
                dimmed ? "opacity-50" : ""
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-foreground">{dayNumber}</span>
                <span aria-hidden="true">{view.glyph}</span>
              </div>
              <p className="mt-1 text-foreground">{view.label}</p>
              {view.detail ? (
                <p className="mt-0.5 break-words text-foreground-muted">{view.detail}</p>
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
    <ul className="flex flex-wrap gap-3 text-xs text-foreground-muted" aria-label="Legend">
      {LEGEND.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className={`inline-flex h-5 w-5 items-center justify-center rounded border ${item.className}`}
          >
            {item.glyph}
          </span>
          {item.label}
        </li>
      ))}
    </ul>
  );
}
