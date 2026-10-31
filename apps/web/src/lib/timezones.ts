import { apiClient } from "@/lib/api/client";

/** Default zone for this product (India-first) — always offered, and always listed first. */
export const DEFAULT_TIMEZONE = "Asia/Kolkata";

const FALLBACK_TIMEZONES = [
  "Asia/Kolkata",
  "UTC",
  "America/New_York",
  "Europe/London",
  "Asia/Singapore",
];

/** Real, always-IANA-valid list sourced from the runtime instead of a hand-maintained (and
 * potentially stale/invalid) list — the backend rejects anything not in `zoneinfo.available_timezones()`.
 * Used for `Branch`/`ShiftVersion` timezone fields, which accept any valid IANA zone (`ED-1`) —
 * NOT for company registration/profile, which is India-gated; see `fetchAllowedCompanyTimezones`. */
export function listTimezones(): string[] {
  let zones = FALLBACK_TIMEZONES;
  if (typeof Intl !== "undefined" && "supportedValuesOf" in Intl) {
    try {
      zones = (
        Intl as unknown as { supportedValuesOf: (key: string) => string[] }
      ).supportedValuesOf("timeZone");
    } catch {
      zones = FALLBACK_TIMEZONES;
    }
  }
  // Indian Standard Time on top, regardless of what the runtime lists (some omit it).
  return [DEFAULT_TIMEZONE, ...zones.filter((tz) => tz !== DEFAULT_TIMEZONE)];
}

/** `DEC-TZ-02` (SELECTED) — the India-only registration/profile allow-list, fetched from the
 * server rather than duplicated as a second hard-coded list (execution gate §6.3: "two
 * independently maintained lists is how they drift"). The backend enforces this regardless of
 * what this returns; a fetch failure falls back to `Asia/Kolkata` alone, matching the server's
 * own default and never silently widening what the form offers. */
export async function fetchAllowedCompanyTimezones(): Promise<string[]> {
  try {
    const data = await apiClient.get<{ allowed_company_timezones: string[] }>(
      "/companies/registration-config",
      { authenticated: false },
    );
    return data.allowed_company_timezones;
  } catch {
    return ["Asia/Kolkata"];
  }
}
