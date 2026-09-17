/** Formatting and business-date helpers shared by the attendance dashboard, employee panel, and
 * day detail page.
 *
 * `formatClockTime`/`formatDateTime` are display-only — never used for calculation, only for
 * rendering values the backend already computed (this claim was inaccurate before this pass:
 * `todayIso()`, a calculation-path date, used to sit in this same file — `NEW-02`, closed by
 * replacing it with `businessToday()`, below).
 *
 * `businessToday()` IS used on a calculation path (`employee-attendance-panel.tsx`'s default
 * `/attendance/days/calculate` date) — it is a business-date derivation, not a display helper,
 * and is documented as such rather than grouped with the two above by proximity alone.
 *
 * `TZ-07` (execution gate §13) — `formatClockTime`/`formatDateTime` took an OPTIONAL `tz` before
 * this pass (in practice, no `tz` at all): `toLocaleTimeString(undefined, {...})` with no
 * `timeZone` option resolves to the VIEWER's own browser/OS timezone. An employee travelling
 * abroad would see their Indian attendance silently reinterpreted in whatever zone their laptop
 * happened to be set to — the exact thing Part 12 of the remediation brief forbids. `tz` is now
 * REQUIRED: an optional parameter with a default is a call site nobody updates (`ED-14`'s own
 * reasoning, applied here too). */

export function formatMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "—";
  const sign = minutes < 0 ? "-" : "";
  const abs = Math.abs(minutes);
  const hours = Math.floor(abs / 60);
  const mins = abs % 60;
  return `${sign}${hours}h ${mins}m`;
}

/** The short, human label Part 12's example (`01 Oct 2026, 05:30 IST`) shows next to a rendered
 * time. Deliberately a small fixed lookup, not a computed abbreviation (`Intl` has no stable,
 * cross-runtime "short zone name" API) — `Asia/Kolkata`/its legacy alias are the only zones
 * India V1 ever resolves to; anything else falls back to the IANA identifier itself rather than
 * guessing at a label. */
export function zoneLabel(tz: string): string {
  if (tz === "Asia/Kolkata" || tz === "Asia/Calcutta") return "IST";
  return tz;
}

export function formatClockTime(iso: string | null | undefined, tz: string): string {
  if (!iso) return "—";
  const time = new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: tz,
  });
  return `${time} ${zoneLabel(tz)}`;
}

export function formatDateTime(iso: string | null | undefined, tz: string): string {
  if (!iso) return "—";
  const value = new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: tz,
  });
  return `${value} ${zoneLabel(tz)}`;
}

/** `TZ-06`/`NEW-02` (execution gate §4, §9, §13) — the one correct replacement for the deleted
 * `todayIso()`, which returned `new Date().toISOString().slice(0, 10)`: the UTC calendar date,
 * unconditionally. Between 00:00 and 05:29 India time, that is one day BEHIND the correct
 * business date — the exact defect this whole programme exists to close, and this file's own
 * header comment (before this fix) claimed these helpers were "never used for calculation" while
 * `todayIso()` sat right here and fed a calculation-path parameter (`employee-attendance-panel.tsx`).
 *
 * `tz` is required, not optional with a default — an optional parameter is a call site nobody
 * updates. Callers get it from `useAuth().user?.company_timezone`. */
export function businessToday(tz: string): string {
  // `en-CA` formats as YYYY-MM-DD — a locale trick, not a real Canadian-locale dependency; every
  // other Intl-supported locale would need explicit part reassembly to get ISO ordering.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function datetimePartsInZone(instant: Date, tz: string): Record<string, string> {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(instant);
  const out: Record<string, string> = {};
  for (const p of parts) out[p.type] = p.value;
  return out;
}

/** `D1` (staging validation report) — the on-behalf punch dialog's time field is labelled with
 * the business timezone (e.g. "Punch time (IST)"), but an `<input type="datetime-local">` value
 * carries no zone of its own: `new Date("2026-09-15T09:00")` interprets it in the VIEWER's
 * browser/OS zone, not the zone the label promises. An admin on a non-IST browser typing `09:00`
 * would record a materially different instant — and a different India business *date* — than
 * the one the label says.
 *
 * Converts a `datetime-local` string, explicitly interpreted as wall-clock time IN `tz`, to the
 * equivalent UTC instant. Uses the standard offset-by-round-trip technique — format a first-guess
 * UTC instant back through `tz`, measure the discrepancy against the wall time that was actually
 * wanted, and correct for it — which is correct even across a DST transition, though
 * `Asia/Kolkata` (`+05:30`, no DST) never has one. Never reads `Date#getTimezoneOffset()` or any
 * other host-clock API, so the browser's own zone cannot influence the result. */
export function wallTimeToUtcIso(datetimeLocal: string, tz: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(datetimeLocal);
  if (!match) {
    throw new Error(`wallTimeToUtcIso: not a datetime-local value: ${datetimeLocal}`);
  }
  const [, y, m, d, hh, mm, ss] = match;
  const guessUtcMs = Date.UTC(
    Number(y),
    Number(m) - 1,
    Number(d),
    Number(hh),
    Number(mm),
    Number(ss ?? "0"),
  );

  const parts = datetimePartsInZone(new Date(guessUtcMs), tz);
  const displayedAsUtcMs = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour),
    Number(parts.minute),
    Number(parts.second),
  );

  const offsetMs = guessUtcMs - displayedAsUtcMs;
  return new Date(guessUtcMs + offsetMs).toISOString();
}

/** The current wall-clock time in `tz`, as a `<input type="datetime-local">` seed value
 * ("YYYY-MM-DDTHH:mm") — the counterpart to `wallTimeToUtcIso` above. Computed via `Intl` with an
 * explicit `timeZone`, never `Date#getTimezoneOffset()`, which reads the VIEWER's own browser
 * zone rather than the business zone the field is labelled with. */
export function nowInZoneForDatetimeLocal(tz: string): string {
  const parts = datetimePartsInZone(new Date(), tz);
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}
