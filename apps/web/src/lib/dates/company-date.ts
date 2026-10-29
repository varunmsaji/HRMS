/**
 * Display-only company dates.
 *
 * The company profile stores `locale.date_format` as a free-form string of at most 20
 * characters. The database default, and the only pattern the product seeds, is `DD/MM/YYYY`.
 * The value is not on the session (`GET /auth/me`), and `GET /companies/current` requires
 * `ORG.COMPANY.MANAGE`, so screens that cannot read the profile use that default.
 *
 * Date-only values (`YYYY-MM-DD`) are calendar dates, not instants. They are parsed as
 * year/month/day parts. `new Date("YYYY-MM-DD")` is UTC midnight and would move the day in
 * timezones behind UTC, so it is never used here.
 *
 * Instants stay on `formatDateTime` / `formatCompanyDateInZone`, which take an explicit IANA
 * timezone. API payloads, `<input type="date">` values, sorting and identifiers stay ISO.
 */

export const DEFAULT_COMPANY_DATE_FORMAT = "DD/MM/YYYY";

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

function isSupportedPattern(pattern: string): boolean {
  const remainder = pattern.replace(/YYYY/gi, "").replace(/DD/gi, "").replace(/MM/gi, "");
  return remainder.length < pattern.length && !/[A-Za-z]/.test(remainder);
}

function resolvePattern(pattern: string | null | undefined): string {
  const candidate = pattern?.trim();
  if (candidate && isSupportedPattern(candidate)) return candidate;
  return DEFAULT_COMPANY_DATE_FORMAT;
}

function isValidYmd(year: number, month: number, day: number): boolean {
  if (year < 1 || month < 1 || month > 12 || day < 1) return false;
  const probe = new Date(Date.UTC(year, month - 1, day));
  return (
    probe.getUTCFullYear() === year && probe.getUTCMonth() === month - 1 && probe.getUTCDate() === day
  );
}

function applyPattern(year: number, month: number, day: number, pattern: string | null | undefined): string {
  const yyyy = String(year).padStart(4, "0");
  const mm = String(month).padStart(2, "0");
  const dd = String(day).padStart(2, "0");
  return resolvePattern(pattern).replace(/YYYY|DD|MM/gi, (token) => {
    const upper = token.toUpperCase();
    if (upper === "YYYY") return yyyy;
    if (upper === "DD") return dd;
    return mm;
  });
}

/** Format a date-only `YYYY-MM-DD` value. Instants, blanks and impossible dates become "—". */
export function formatCompanyDate(
  value: string | null | undefined,
  pattern: string | null | undefined = DEFAULT_COMPANY_DATE_FORMAT,
): string {
  if (value == null) return "—";
  const match = DATE_ONLY.exec(value.trim());
  if (!match) return "—";
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (!isValidYmd(year, month, day)) return "—";
  return applyPattern(year, month, day, pattern);
}

/** Calendar date of an instant in `tz`, using the company pattern. */
export function formatCompanyDateInZone(
  iso: string | null | undefined,
  tz: string,
  pattern: string | null | undefined = DEFAULT_COMPANY_DATE_FORMAT,
): string {
  if (!iso) return "—";
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(instant);
  const year = Number(parts.find((part) => part.type === "year")?.value);
  const month = Number(parts.find((part) => part.type === "month")?.value);
  const day = Number(parts.find((part) => part.type === "day")?.value);
  if (!isValidYmd(year, month, day)) return "—";
  return applyPattern(year, month, day, pattern);
}
