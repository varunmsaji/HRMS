"use client";

import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";

/** True for people with an employee record but no company-dashboard access — they get the
 * personal workday layout (same rule the dashboard page uses to pick its view). */
export function useEmployeeMode(): boolean {
  const { user } = useAuth();
  const { can } = usePermissions();
  return Boolean(user?.employee_id) && !can("DASHBOARD.COMPANY.VIEW");
}
