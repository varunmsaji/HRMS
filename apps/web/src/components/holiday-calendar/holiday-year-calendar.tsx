"use client";

import type { Holiday } from "@/lib/holiday-calendar/types";

const WEEKDAYS = ["M", "T", "W", "T", "F", "S", "S"];
const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

interface Props {
  year: number;
  holidays: Holiday[];
  /** When provided, empty days are clickable (used to add a holiday on that date). */
  onDayClick?: (isoDate: string) => void;
}

/** Twelve-month calendar for one year with holiday dates highlighted. Past days are dimmed. */
export function HolidayYearCalendar({ year, holidays, onDayClick }: Props) {
  const byDate = new Map<string, Holiday[]>();
  for (const h of holidays) {
    if (!h.is_active) continue;
    byDate.set(h.date, [...(byDate.get(h.date) ?? []), h]);
  }
  const now = new Date();
  const today = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {MONTHS.map((monthName, m) => {
        const offset = (new Date(year, m, 1).getDay() + 6) % 7; // Monday-first
        const daysInMonth = new Date(year, m + 1, 0).getDate();
        const cells: (number | null)[] = [
          ...Array.from({ length: offset }, () => null),
          ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
        ];
        return (
          <div key={monthName} className="rounded-md border border-border p-3">
            <p className="mb-2 text-sm font-medium text-foreground">{monthName}</p>
            <div className="grid grid-cols-7 gap-1 text-center text-xs">
              {WEEKDAYS.map((d, i) => (
                <span key={i} className="text-foreground-muted">
                  {d}
                </span>
              ))}
              {cells.map((day, i) => {
                if (day === null) return <span key={`b${i}`} />;
                const iso = `${year}-${pad(m + 1)}-${pad(day)}`;
                const hs = byDate.get(iso);
                const past = iso < today;
                const isToday = iso === today;
                const base = "flex h-7 items-center justify-center rounded text-xs";
                const tone = hs
                  ? "bg-primary text-white font-medium"
                  : past
                    ? "text-foreground-muted"
                    : "text-foreground";
                const ring = isToday ? " ring-1 ring-primary" : "";
                const title = hs?.map((h) => h.name).join(", ");
                if (!hs && onDayClick) {
                  return (
                    <button
                      key={iso}
                      type="button"
                      title="Add holiday"
                      aria-label={`Add holiday on ${iso}`}
                      className={`${base} ${tone}${ring} hover:bg-surface-secondary`}
                      onClick={() => onDayClick(iso)}
                    >
                      {day}
                    </button>
                  );
                }
                return (
                  <span key={iso} title={title} className={`${base} ${tone}${ring}`}>
                    {day}
                  </span>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
