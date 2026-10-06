"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AttendancePeriod, AttendancePeriodSummaryRow } from "@/lib/attendance-period/types";
import type { AttendanceDay } from "@/lib/attendance/types";
import type { DateRange, EmployeeLite } from "@/lib/attendance/dashboard";
import type { LegalEntity } from "@/lib/legal-entity/types";
import type { OvertimeRecord } from "@/lib/overtime/types";
import type { RegularizationRequest } from "@/lib/regularization/types";
import type { Shift } from "@/lib/shift/types";

export interface Section<T> {
  status: "idle" | "loading" | "ready" | "error";
  data: T | null;
  error: ApiError | null;
  retry: () => void;
}

export function toApiError(err: unknown): ApiError {
  return err instanceof ApiError
    ? err
    : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." });
}

/** Loads one independent dashboard section. `key` identifies the inputs (a changed key reloads);
 * `enabled=false` leaves the section idle without a request. Each section fails on its own, so one
 * broken or permission-denied panel never blanks the rest of the dashboard. */
export function useSection<T>(loader: () => Promise<T>, key: string, enabled: boolean): Section<T> {
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const [state, setState] = useState<Omit<Section<T>, "retry">>({
    status: enabled ? "loading" : "idle",
    data: null,
    error: null,
  });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState((prev) => ({ ...prev, status: "loading", error: null }));
    loaderRef
      .current()
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data, error: null });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ status: "error", data: null, error: toApiError(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [key, nonce, enabled]);

  const retry = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, retry };
}

const EMPLOYEE_PAGE_SIZE = 100;
/** Pages beyond this are not fetched — the dashboard says so instead of silently truncating. */
const EMPLOYEE_MAX_PAGES = 5;

export interface EmployeeDirectory {
  items: EmployeeLite[];
  total: number;
  truncated: boolean;
}

async function loadEmployees(): Promise<EmployeeDirectory> {
  const first = await apiClient.getList<EmployeeLite>("/employees", { page: 1, per_page: EMPLOYEE_PAGE_SIZE });
  const items = [...first.data];
  const totalPages = first.pagination?.total_pages ?? 1;
  const lastPage = Math.min(totalPages, EMPLOYEE_MAX_PAGES);
  if (lastPage > 1) {
    const rest = await Promise.all(
      Array.from({ length: lastPage - 1 }, (_, i) =>
        apiClient.getList<EmployeeLite>("/employees", { page: i + 2, per_page: EMPLOYEE_PAGE_SIZE }),
      ),
    );
    for (const page of rest) items.push(...page.data);
  }
  return {
    items,
    total: first.pagination?.total ?? items.length,
    truncated: totalPages > EMPLOYEE_MAX_PAGES,
  };
}

export interface DashboardDataInput {
  window: DateRange;
  range: DateRange;
  legalEntityId: string;
  canListEmployees: boolean;
  canListShifts: boolean;
  canListEntities: boolean;
  /** Org-level panels (periods, pending queues) — not requested for a plain employee view. */
  loadOperational: boolean;
}

export interface DashboardData {
  days: Section<AttendanceDay[]>;
  employees: Section<EmployeeDirectory>;
  regularizations: Section<RegularizationRequest[]>;
  overtime: Section<OvertimeRecord[]>;
  periods: Section<AttendancePeriod[]>;
  entities: Section<LegalEntity[]>;
  shifts: Section<Shift[]>;
}

/** Request plan — deliberately small. Primary (parallel): attendance days for the whole window
 * (every KPI, chart, list and the muster derive from this one response) and the employee
 * directory. Secondary (after the primary days land): pending regularizations, overtime records,
 * attendance periods, and the two optional lookups. About 7 requests, never one per employee. */
export function useDashboardData(input: DashboardDataInput): DashboardData {
  const { window, range, legalEntityId } = input;

  const days = useSection<AttendanceDay[]>(
    () =>
      apiClient.get<AttendanceDay[]>(
        `/attendance/days?${new URLSearchParams({ date_from: window.from, date_to: window.to }).toString()}`,
      ),
    `${window.from}|${window.to}`,
    true,
  );
  const employees = useSection<EmployeeDirectory>(loadEmployees, "employees", input.canListEmployees);

  const [coreSettled, setCoreSettled] = useState(false);
  useEffect(() => {
    if (days.status === "ready") setCoreSettled(true);
  }, [days.status]);
  const secondary = coreSettled && input.loadOperational;

  const regularizations = useSection<RegularizationRequest[]>(
    () => apiClient.get<RegularizationRequest[]>("/regularizations?request_status=SUBMITTED"),
    "regularizations",
    secondary,
  );
  const overtime = useSection<OvertimeRecord[]>(
    () =>
      apiClient.get<OvertimeRecord[]>(
        `/overtime?${new URLSearchParams({ date_from: range.from, date_to: range.to }).toString()}`,
      ),
    `${range.from}|${range.to}`,
    secondary,
  );
  const periods = useSection<AttendancePeriod[]>(
    () =>
      apiClient.get<AttendancePeriod[]>(
        legalEntityId
          ? `/attendance-periods?${new URLSearchParams({ legal_entity_id: legalEntityId }).toString()}`
          : "/attendance-periods",
      ),
    `periods|${legalEntityId}`,
    secondary,
  );
  const entities = useSection<LegalEntity[]>(
    () => apiClient.get<LegalEntity[]>("/legal-entities"),
    "entities",
    secondary && input.canListEntities,
  );
  const shifts = useSection<Shift[]>(
    () => apiClient.get<Shift[]>("/shifts"),
    "shifts",
    coreSettled && input.canListShifts,
  );

  return { days, employees, regularizations, overtime, periods, entities, shifts };
}

export function usePeriodSummary(periodId: string | null): Section<AttendancePeriodSummaryRow[]> {
  return useSection<AttendancePeriodSummaryRow[]>(
    () => apiClient.get<AttendancePeriodSummaryRow[]>(`/attendance-periods/${periodId}/summary`),
    `summary|${periodId}`,
    periodId !== null,
  );
}
