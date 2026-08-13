const FALLBACK_TIMEZONES = ["Asia/Kolkata", "UTC", "America/New_York", "Europe/London", "Asia/Singapore"];

/** Real, always-IANA-valid list sourced from the runtime instead of a hand-maintained (and
 * potentially stale/invalid) list — the backend rejects anything not in `zoneinfo.available_timezones()`. */
export function listTimezones(): string[] {
  if (typeof Intl !== "undefined" && "supportedValuesOf" in Intl) {
    try {
      return (Intl as unknown as { supportedValuesOf: (key: string) => string[] }).supportedValuesOf(
        "timeZone",
      );
    } catch {
      return FALLBACK_TIMEZONES;
    }
  }
  return FALLBACK_TIMEZONES;
}
