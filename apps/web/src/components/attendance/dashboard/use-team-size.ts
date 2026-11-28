"use client";

import { useEffect, useState } from "react";

import { apiClient } from "@/lib/api/client";

export interface TeamSize {
  /** `idle` when nobody asked (the caller sees everyone, or has no employee record). */
  status: "idle" | "loading" | "ready" | "error";
  /** How many people report to the caller directly; only meaningful when `ready`. */
  total: number;
}

interface Answer {
  forId: string;
  status: "ready" | "error";
  total: number;
}

/** How many direct reports `employeeId` has: the signal that the caller manages a team, so the
 * page can say so before (and whether or not) any attendance rows come back. One request for one
 * row, as only the total is read. A failed lookup is `error`, and the page falls back to reading
 * the attendance rows themselves. */
export function useTeamSize(employeeId: string | null, enabled: boolean): TeamSize {
  const [answer, setAnswer] = useState<Answer | null>(null);
  const active = enabled && employeeId !== null;

  useEffect(() => {
    if (!active || employeeId === null) return;
    let cancelled = false;
    apiClient
      .getList<unknown>(`/employees/${employeeId}/direct-reports`, { page: 1, per_page: 1 })
      .then((res) => {
        if (!cancelled) setAnswer({ forId: employeeId, status: "ready", total: res.pagination?.total ?? res.data.length });
      })
      .catch(() => {
        if (!cancelled) setAnswer({ forId: employeeId, status: "error", total: 0 });
      });
    return () => {
      cancelled = true;
    };
  }, [active, employeeId]);

  if (!active) return { status: "idle", total: 0 };
  if (answer === null || answer.forId !== employeeId) return { status: "loading", total: 0 };
  return { status: answer.status, total: answer.total };
}
