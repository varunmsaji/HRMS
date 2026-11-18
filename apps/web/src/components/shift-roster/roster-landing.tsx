"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { usePermissions } from "@/lib/auth/use-permissions";

import { COVERAGE_HREF, lastViewHref } from "./roster-nav";

/** Where the roster addresses lead to.
 *
 * - `to="coverage"` (the default, `/app/rosters` and the sidebar's Shift Rosters): Coverage, the
 *   overview, for everyone.
 * - `to="schedule"` (`/app/rosters/schedule`, kept so old bookmarks still work): the schedule view
 *   you used last (Week the first time). Staff who cannot manage rosters only have Coverage, so
 *   they go there. */
export function RosterLanding({ to = "coverage" }: { to?: "coverage" | "schedule" }) {
  const router = useRouter();
  const { can } = usePermissions();
  const canManage = can("ATTENDANCE.ROSTER_MANAGE");

  useEffect(() => {
    router.replace(to === "schedule" && canManage ? lastViewHref() : COVERAGE_HREF);
  }, [router, canManage, to]);

  return (
    <div role="status" aria-label="Opening shift rosters" className="py-10 text-center text-sm text-foreground-secondary">
      Opening shift rosters…
    </div>
  );
}
