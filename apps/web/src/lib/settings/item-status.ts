import { useEffect, useState } from "react";

import { apiClient } from "@/lib/api/client";

export type ItemStatusTone = "ok" | "warning" | "muted";

export interface ItemStatus {
  text: string;
  tone: ItemStatusTone;
}

interface Listed {
  is_active?: boolean;
  status?: string;
  live_from?: string | null;
  assigned_company_wide?: boolean;
  assigned_group_count?: number;
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Counts the active rows of a list; `essential` lists warn when empty. */
function countOf(path: string, one: string, many?: string, essential = false) {
  return async (): Promise<ItemStatus> => {
    const rows = (await apiClient.get<Listed[]>(path)).filter((r) => r.is_active !== false);
    if (rows.length === 0) {
      return { text: essential ? "None yet: needed" : "None yet", tone: essential ? "warning" : "muted" };
    }
    return { text: plural(rows.length, one, many), tone: "ok" };
  };
}

/** Policies: how many are live, and how many of those nobody follows. */
function policiesOf(path: string, essential = false) {
  return async (): Promise<ItemStatus> => {
    const rows = (await apiClient.get<Listed[]>(path)).filter((r) => r.is_active !== false);
    if (rows.length === 0) {
      return { text: essential ? "None yet: needed" : "None yet", tone: essential ? "warning" : "muted" };
    }
    const unassigned = rows.filter(
      (r) => r.live_from && !r.assigned_company_wide && !(r.assigned_group_count ?? 0),
    ).length;
    const base = plural(rows.length, "policy", "policies");
    return unassigned > 0
      ? { text: `${base} · ${unassigned} not assigned`, tone: "warning" }
      : { text: base, tone: "ok" };
  };
}

function totalOf(path: string, one: string, many?: string) {
  return async (): Promise<ItemStatus> => {
    const { pagination } = await apiClient.getList<unknown>(path, { per_page: 1 });
    const total = pagination?.total ?? 0;
    return total === 0 ? { text: "None yet", tone: "muted" } : { text: plural(total, one, many), tone: "ok" };
  };
}

const LOADERS: Record<string, () => Promise<ItemStatus>> = {
  "/app/legal-entities": countOf("/legal-entities", "legal entity", "legal entities", true),
  "/app/branches": countOf("/branches", "branch", "branches"),
  "/app/departments": countOf("/departments", "department"),
  "/app/designations": countOf("/designations", "designation"),
  "/app/grades": countOf("/grades", "grade"),
  "/app/shifts": countOf("/shifts", "shift", undefined, true),
  "/app/work-calendars": countOf("/work-calendars", "calendar", undefined, true),
  "/app/holiday-calendars": countOf("/holiday-calendars", "calendar"),
  "/app/weekly-off-patterns": countOf("/weekly-off-patterns", "pattern"),
  "/app/attendance-geofences": totalOf("/attendance/geofences", "workplace"),
  "/app/attendance-policies": policiesOf("/attendance-policies", true),
  "/app/overtime-policies": policiesOf("/overtime-policies"),
  "/app/regularization-policies": policiesOf("/regularization-policies"),
  "/app/attendance-periods": async () => {
    const rows = await apiClient.get<Listed[]>("/attendance-periods");
    const open = rows.filter((r) => r.status === "OPEN").length;
    if (rows.length === 0) return { text: "No months yet", tone: "muted" };
    return { text: open === 0 ? "All months closed" : `${plural(open, "month")} open`, tone: "ok" };
  },
  "/app/leave-types": countOf("/leave-types", "leave type"),
  "/app/leave-policies": policiesOf("/leave-policies"),
  "/app/payroll/salary-components": countOf("/payroll/salary-components", "component"),
  "/app/payroll/salary-structures": countOf("/payroll/salary-structures", "structure"),
  "/app/users": totalOf("/users", "user"),
};

export function hasItemStatus(href: string): boolean {
  return href in LOADERS;
}

/** A short live summary of one Settings screen, e.g. "3 shifts" or "2 policies · 1 not
 * assigned". `null` while loading, for screens without one, or when it can't be read (no
 * permission, network) — the card then simply shows no status. */
export function useItemStatus(href: string, enabled = true): ItemStatus | null {
  const [status, setStatus] = useState<{ href: string; value: ItemStatus | null } | null>(null);
  const load = enabled ? LOADERS[href] : undefined;

  useEffect(() => {
    if (!load) return;
    let current = true;
    load()
      .then((value) => {
        if (current) setStatus({ href, value });
      })
      .catch(() => {
        if (current) setStatus({ href, value: null });
      });
    return () => {
      current = false;
    };
  }, [href, load]);

  return status?.href === href ? status.value : null;
}
