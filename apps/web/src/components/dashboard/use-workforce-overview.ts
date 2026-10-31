"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { isAbortError, useLatestRequest } from "@/hooks/use-latest-request";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AttendanceOverview } from "@/lib/dashboard/overview";

interface Options {
  /** ISO date; empty string means "today" (the server resolves it in the company timezone). */
  date: string;
  departmentId: string;
  branchId: string;
  enabled: boolean;
}

/** Loads the workforce overview. A refresh or filter change keeps the previous figures on screen
 * (`refreshing`) instead of blanking the section; an older, slower response can never overwrite a
 * newer one, and overlapping triggers cancel the in-flight request. */
export function useWorkforceOverview({ date, departmentId, branchId, enabled }: Options) {
  const begin = useLatestRequest();
  const [data, setData] = useState<AttendanceOverview | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);
  const hasData = useRef(false);

  const load = useCallback(async () => {
    if (!enabled) return;
    const request = begin();
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (date) params.set("date", date);
      if (departmentId) params.set("department_id", departmentId);
      if (branchId) params.set("branch_id", branchId);
      const qs = params.toString();
      const next = await apiClient.get<AttendanceOverview>(
        `/dashboards/company/attendance-overview${qs ? `?${qs}` : ""}`,
        { signal: request.signal },
      );
      if (!request.isCurrent()) return;
      hasData.current = true;
      setData(next);
      setFetchedAt(new Date());
    } catch (err) {
      if (isAbortError(err) || !request.isCurrent()) return;
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      if (request.isCurrent()) setLoading(false);
    }
  }, [begin, date, departmentId, branchId, enabled]);

  useEffect(() => {
    void load();
  }, [load]);

  return {
    data,
    error,
    /** First load, with nothing to show yet. */
    initialLoading: loading && !data,
    /** Re-fetching while the previous figures stay visible. */
    refreshing: loading && !!data,
    fetchedAt,
    refresh: load,
  };
}
