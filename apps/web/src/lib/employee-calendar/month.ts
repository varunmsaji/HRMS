/** Date-only helpers for the employee calendar. Every value is a `YYYY-MM-DD` string (or a
 * `YYYY-MM` month key) and all arithmetic is done in UTC on `Date.UTC(...)` values, so the
 * viewer's browser timezone can never move a date by a day. */

const DAY_MS = 86_400_000;

function parseIso(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function toIso(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** `YYYY-MM` of a `YYYY-MM-DD` date. */
export function monthKeyOf(iso: string): string {
  return iso.slice(0, 7);
}

/** `delta` months from a `YYYY-MM` key (negative goes back). */
export function shiftMonth(monthKey: string, delta: number): string {
  const [y, m] = monthKey.split("-").map(Number);
  const shifted = new Date(Date.UTC(y, m - 1 + delta, 1));
  return toIso(shifted).slice(0, 7);
}

/** The Monday-first week grid covering a month: from the Monday on or before the 1st to the
 * Sunday on or after the last day (at most 42 days, inside the API's 100-day limit). */
export function gridRangeForMonth(monthKey: string): { from: string; to: string } {
  const first = parseIso(`${monthKey}-01`);
  const last = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0));
  const lead = (first.getUTCDay() + 6) % 7;
  const trail = 6 - ((last.getUTCDay() + 6) % 7);
  return {
    from: toIso(new Date(first.getTime() - lead * DAY_MS)),
    to: toIso(new Date(last.getTime() + trail * DAY_MS)),
  };
}

/** Every date from `from` to `to`, inclusive, grouped into Monday-first weeks. */
export function weeksBetween(from: string, to: string): string[][] {
  const weeks: string[][] = [];
  let week: string[] = [];
  for (let t = parseIso(from).getTime(); t <= parseIso(to).getTime(); t += DAY_MS) {
    week.push(toIso(new Date(t)));
    if (week.length === 7) {
      weeks.push(week);
      week = [];
    }
  }
  if (week.length > 0) weeks.push(week);
  return weeks;
}

/** "October 2026" for a `YYYY-MM` key, independent of the viewer's timezone. */
export function formatMonthLabel(monthKey: string): string {
  return new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric", timeZone: "UTC" }).format(
    parseIso(`${monthKey}-01`),
  );
}

/** "Wednesday, 9 September 2026" for a `YYYY-MM-DD` date, independent of the viewer's timezone. */
export function formatLongDate(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(parseIso(iso));
}
