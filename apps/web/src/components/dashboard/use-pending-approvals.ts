"use client";

import { useCallback, useEffect, useState } from "react";

import { isAbortError, useLatestRequest } from "@/hooks/use-latest-request";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { LeaveApplication } from "@/lib/leave-application/types";
import type { OnboardingCase } from "@/lib/onboarding/types";
import type { OvertimeRecord } from "@/lib/overtime/types";
import type { RegularizationRequest } from "@/lib/regularization/types";
import { ONBOARDING_CANDIDATE_STATUSES, ONBOARDING_HR_STATUSES } from "@/lib/dashboard/overview";

/** Rows shown per category; the count is the list endpoint's own `total`. */
export const PENDING_PREVIEW_SIZE = 5;

export interface PendingCategory<T> {
  total: number;
  items: T[];
  error: ApiError | null;
}

export interface PendingApprovals {
  leave: PendingCategory<LeaveApplication> | null;
  regularization: PendingCategory<RegularizationRequest> | null;
  overtime: PendingCategory<OvertimeRecord> | null;
  onboardingHr: PendingCategory<OnboardingCase> | null;
  onboardingCandidate: PendingCategory<OnboardingCase> | null;
}

interface Enabled {
  leave: boolean;
  regularization: boolean;
  overtime: boolean;
  onboarding: boolean;
}

function toError(err: unknown): ApiError {
  return err instanceof ApiError
    ? err
    : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." });
}

async function fetchCategory<T>(
  path: string,
  query: Record<string, string | number>,
  signal: AbortSignal,
): Promise<PendingCategory<T>> {
  try {
    const { data, pagination } = await apiClient.getList<T>(
      path,
      { page: 1, per_page: PENDING_PREVIEW_SIZE, ...query },
      { signal },
    );
    return { items: data, total: pagination?.total ?? data.length, error: null };
  } catch (err) {
    if (isAbortError(err)) throw err;
    return { items: [], total: 0, error: toError(err) };
  }
}

/** One onboarding bucket spans several workflow statuses; the list endpoint filters on one, so
 * the per-status results are merged (totals add — a case has exactly one status). */
async function fetchOnboarding(
  statuses: readonly string[],
  signal: AbortSignal,
): Promise<PendingCategory<OnboardingCase>> {
  const parts = await Promise.all(
    statuses.map((status) => fetchCategory<OnboardingCase>("/onboarding-cases", { status }, signal)),
  );
  return {
    total: parts.reduce((sum, p) => sum + p.total, 0),
    items: parts
      .flatMap((p) => p.items)
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
      .slice(0, PENDING_PREVIEW_SIZE),
    error: parts.find((p) => p.error)?.error ?? null,
  };
}

/** Pending approval queues, always "pending now" — independent of the attendance date picker.
 * Counts come straight from the existing list endpoints (`pagination.total`), which already apply
 * the caller's data scope, so they equal the module queues. A category the caller cannot approve
 * is never requested. Each category fails independently. */
export function usePendingApprovals(enabled: Enabled) {
  const begin = useLatestRequest();
  const [data, setData] = useState<PendingApprovals | null>(null);
  const [loading, setLoading] = useState(true);

  const { leave, regularization, overtime, onboarding } = enabled;

  const load = useCallback(async () => {
    const request = begin();
    setLoading(true);
    try {
      const [l, r, o, hr, cand] = await Promise.all([
        leave
          ? fetchCategory<LeaveApplication>("/leave-applications", { application_status: "SUBMITTED" }, request.signal)
          : null,
        regularization
          ? fetchCategory<RegularizationRequest>("/regularizations", { request_status: "SUBMITTED" }, request.signal)
          : null,
        overtime
          ? fetchCategory<OvertimeRecord>("/overtime", { record_status: "PENDING" }, request.signal)
          : null,
        onboarding ? fetchOnboarding(ONBOARDING_HR_STATUSES, request.signal) : null,
        onboarding ? fetchOnboarding(ONBOARDING_CANDIDATE_STATUSES, request.signal) : null,
      ]);
      if (!request.isCurrent()) return;
      setData({ leave: l, regularization: r, overtime: o, onboardingHr: hr, onboardingCandidate: cand });
    } catch (err) {
      if (!isAbortError(err)) throw err;
    } finally {
      if (request.isCurrent()) setLoading(false);
    }
  }, [begin, leave, regularization, overtime, onboarding]);

  useEffect(() => {
    void load();
  }, [load]);

  return { data, loading, refresh: load };
}
