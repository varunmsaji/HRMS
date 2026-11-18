"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { usePermissions } from "@/lib/auth/use-permissions";

import { COVERAGE_HREF, lastViewHref } from "./roster-nav";

/** What `/app/rosters` and `/app/rosters/schedule` lead to: the schedule view you used last (Week
 * the first time). Staff who cannot manage rosters only have Coverage, so they go there. */
export function RosterLanding() {
  const router = useRouter();
  const { can } = usePermissions();
  const canManage = can("ATTENDANCE.ROSTER_MANAGE");

  useEffect(() => {
    router.replace(canManage ? lastViewHref() : COVERAGE_HREF);
  }, [router, canManage]);

  return (
    <div role="status" aria-label="Opening shift rosters" className="py-10 text-center text-sm text-foreground-secondary">
      Opening shift rosters…
    </div>
  );
}
