"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AttendancePeriod, AttendancePeriodSummaryRow } from "@/lib/attendance-period/types";
import type { AttendanceDay } from "@/lib/attendance/types";
import type { DashboardFilters, DateRange, EmployeeLite } from "@/lib/attendance/dashboard";
import { summaryQuery, type AttendanceSummary } from "@/lib/attendance/summary";
import { directoryRowsPath, type DirectoryRow } from "@/lib/employee/directory";
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

/** The API returns at most this many attendance days per page. */
const DAYS_PAGE_SIZE = 500;
/** 10,000 rows (the same ceiling the mobile app uses); beyond it the dashboard says it is partial. */
const DAYS_MAX_PAGES = 20;

export interface DaysCoverage {
  loaded: number;
  total: number;
  truncated: boolean;
}

interface DayList {
  items: AttendanceDay[];
  coverage: DaysCoverage;
}

/** Every attendance day in `window`, across all pages. The list is newest first, so reading only
 * the first page silently dropped the older days of the window from every trend and total once
 * a company had more than about 35 employees. */
export async function loadDays(window: DateRange): Promise<DayList> {
  const query = { date_from: window.from, date_to: window.to, per_page: DAYS_PAGE_SIZE };
  const first = await apiClient.getList<AttendanceDay>("/attendance/days", { ...query, page: 1 });
  const items = [...first.data];
  const totalPages = first.pagination?.total_pages ?? 1;
  const lastPage = Math.min(totalPages, DAYS_MAX_PAGES);
  if (lastPage > 1) {
    const rest = await Promise.all(
      Array.from({ length: lastPage - 1 }, (_, i) =>
        apiClient.getList<AttendanceDay>("/attendance/days", { ...query, page: i + 2 }),
      ),
    );
    for (const page of rest) items.push(...page.data);
  }
  const total = first.pagination?.total ?? items.length;
  return { items, coverage: { loaded: items.length, total, truncated: totalPages > DAYS_MAX_PAGES } };
}

export interface DashboardDataInput {
  window: DateRange;
  range: DateRange;
  /** The population filters the summary's totals are counted over. */
  filters: DashboardFilters;
  legalEntityId: string;
  canListEmployees: boolean;
  canListShifts: boolean;
  canListEntities: boolean;
  /** Org-level panels (periods, pending queues) — not requested for a plain employee view. */
  loadOperational: boolean;
}

export interface DashboardData {
  /** The window's totals, counted by the backend (KPIs, rates, trend, punctuality, breakdown). */
  summary: Section<AttendanceSummary>;
  days: Section<AttendanceDay[]>;
  /** How many of the window's attendance days were loaded; `null` until they have. */
  daysCoverage: DaysCoverage | null;
  employees: Section<EmployeeDirectory>;
  regularizations: Section<RegularizationRequest[]>;
  overtime: Section<OvertimeRecord[]>;
  periods: Section<AttendancePeriod[]>;
  entities: Section<LegalEntity[]>;
  shifts: Section<Shift[]>;
}

/** Request plan — deliberately small. Primary (parallel): the summary (every total and chart,
 * counted by the backend; re-read when a population filter changes), the attendance days for the
 * whole window (the per-person lists and the muster) and the employee directory. Secondary (after
 * the primary days land): pending regularizations, overtime records, attendance periods, and the
 * two optional lookups. About 8 requests, never one per employee. */
export function useDashboardData(input: DashboardDataInput): DashboardData {
  const { window, range, legalEntityId } = input;

  const query = summaryQuery(window, input.filters);
  const summary = useSection<AttendanceSummary>(
    () => apiClient.get<AttendanceSummary>(`/attendance/summary?${new URLSearchParams(query).toString()}`),
    `summary|${new URLSearchParams(query).toString()}`,
    true,
  );

  const dayList = useSection<DayList>(() => loadDays(window), `${window.from}|${window.to}`, true);
  const days = useMemo<Section<AttendanceDay[]>>(
    () => ({
      status: dayList.status,
      data: dayList.data?.items ?? null,
      error: dayList.error,
      retry: dayList.retry,
    }),
    [dayList.status, dayList.data, dayList.error, dayList.retry],
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

  return {
    summary,
    days,
    daysCoverage: dayList.data?.coverage ?? null,
    employees,
    regularizations,
    overtime,
    periods,
    entities,
    shifts,
  };
}

export function usePeriodSummary(periodId: string | null): Section<AttendancePeriodSummaryRow[]> {
  return useSection<AttendancePeriodSummaryRow[]>(
    () => apiClient.get<AttendancePeriodSummaryRow[]>(`/attendance-periods/${periodId}/summary`),
    `summary|${periodId}`,
    periodId !== null,
  );
}

/** The directory endpoint takes at most 200 ids per request. */
const DIRECTORY_CHUNK = 200;
/** A hard ceiling on requests (2,000 employees); beyond it the result says it is partial. */
const DIRECTORY_MAX_CHUNKS = 10;

export interface DirectoryDetails {
  /** Department, branch, designation… keyed by employee id. */
  byEmployee: Map<string, DirectoryRow>;
  /** True when there were more employees than the ceiling allows — figures cover only some. */
  truncated: boolean;
  /** How many employees the figures cover, and how many there were. */
  covered: number;
  total: number;
}

async function loadDirectoryDetails(ids: string[]): Promise<DirectoryDetails> {
  const limit = DIRECTORY_CHUNK * DIRECTORY_MAX_CHUNKS;
  const wanted = ids.slice(0, limit);
  const chunks: string[][] = [];
  for (let i = 0; i < wanted.length; i += DIRECTORY_CHUNK) chunks.push(wanted.slice(i, i + DIRECTORY_CHUNK));
  const pages = await Promise.all(chunks.map((chunk) => apiClient.get<DirectoryRow[]>(directoryRowsPath(chunk))));
  const byEmployee = new Map<string, DirectoryRow>();
  for (const rows of pages) for (const row of rows) byEmployee.set(row.employee_id, row);
  return { byEmployee, truncated: ids.length > limit, covered: wanted.length, total: ids.length };
}

/** A short stable fingerprint of a set of ids, so the section reloads when the people change but
 * not when the same people are listed in another order. */
function fingerprint(ids: string[]): string {
  let hash = 2166136261;
  for (const id of [...ids].sort()) {
    for (let i = 0; i < id.length; i += 1) {
      hash ^= id.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
  }
  return `${ids.length}:${(hash >>> 0).toString(16)}`;
}

/** Department / branch for the given employees, from the employee directory. Requests are batched
 * (never one per employee) and run in parallel. Needs the same permission as the employee list. */
export function useDirectoryDetails(employeeIds: string[], enabled: boolean): Section<DirectoryDetails> {
  return useSection<DirectoryDetails>(
    () => loadDirectoryDetails(employeeIds),
    `directory|${fingerprint(employeeIds)}`,
    enabled && employeeIds.length > 0,
  );
}
