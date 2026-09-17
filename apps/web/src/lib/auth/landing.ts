import type { UserProfile } from "@/lib/auth/types";

/** Where to send a user right after login/registration/invite-acceptance. A `COMPANY_ADMIN`/
 * `HR_ADMIN`-shaped user holds `DASHBOARD.COMPANY.VIEW` and goes to the company dashboard, same
 * as always. An `EMPLOYEE`/`REPORTING_MANAGER`-shaped user doesn't hold that permission — sending
 * them to `/app/dashboard` anyway would land them on a page that immediately shows "You do not
 * have permission" (doc 41 Phase 4 addendum, verified in-browser). Send them to their own profile
 * instead, when one exists. */
export function landingPathFor(user: UserProfile | null): string {
  if (user?.permissions.includes("DASHBOARD.COMPANY.VIEW")) return "/app/dashboard";
  if (user?.employee_id) return "/app/me";
  return "/app/dashboard";
}
