import { useEffect, useState } from "react";

import { apiClient } from "@/lib/api/client";

/** Default zone for this product (India-first) — always offered, and always listed first. */
export const DEFAULT_TIMEZONE = "Asia/Kolkata";

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

/** SH-06 — the zones a company, branch or shift may use: the same server allow-list as
 * registration (a branch or shift zone outranks the company's, so offering every IANA zone here
 * let a shift run 5½ hours off). Starts as `Asia/Kolkata` alone until the fetch returns. `current`
 * (the stored value) is always kept so an older row still shows what it holds. */
export function useAllowedTimezones(current?: string | null): string[] {
  const [allowed, setAllowed] = useState<string[]>([DEFAULT_TIMEZONE]);
  useEffect(() => {
    let cancelled = false;
    void fetchAllowedCompanyTimezones().then((zones) => {
      if (!cancelled && zones.length > 0) setAllowed(zones);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const ordered = [DEFAULT_TIMEZONE, ...allowed.filter((tz) => tz !== DEFAULT_TIMEZONE)];
  return current && !ordered.includes(current) ? [...ordered, current] : ordered;
}
