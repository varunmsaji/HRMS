"use client";

import { useMemo } from "react";

import { useAuth } from "@/lib/auth/auth-context";

/**
 * The backend is the sole authority on permissions and data scope (`docs/product/19_RBAC_and_
 * Permission_Matrix.md`) — this hook only reads the flat `permissions: string[]` list `/auth/me`
 * already returns (`UserProfile.permissions`), so the UI can decide whether to *show* an action
 * before round-tripping to the server. It never blocks a request itself; a 403 response is still
 * the actual enforcement and must still be handled wherever a request is made. This is the
 * smallest mechanism that covers "hide actions the user very likely can't perform" without
 * building a second authorization system.
 */
export function usePermissions() {
  const { user } = useAuth();

  return useMemo(() => {
    const permissions = new Set(user?.permissions ?? []);
    return {
      permissions,
      can: (code: string) => permissions.has(code),
      canAny: (codes: string[]) => codes.some((code) => permissions.has(code)),
    };
  }, [user]);
}
