"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { isAbortError, useLatestRequest } from "@/hooks/use-latest-request";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

/** The few `Employee` fields a picker or a name column needs. */
export interface EmployeeOption {
  id: string;
  first_name: string;
  last_name: string | null;
  employee_code: string | null;
  display_name?: string | null;
}

export function employeeOptionName(employee: EmployeeOption): string {
  const name =
    employee.display_name?.trim() ||
    [employee.first_name, employee.last_name].filter(Boolean).join(" ");
  return employee.employee_code ? `${name} (${employee.employee_code})` : name;
}

/** Server page size for the directory. `GET /employees` is capped at 100 rows per page. */
export const EMPLOYEE_DIRECTORY_PAGE_SIZE = 100;

export interface EmployeeDirectory {
  /** Every employee loaded so far — a prefix of the server's list, NOT necessarily everyone. */
  employees: EmployeeOption[];
  /** Total number of employees the caller may see, from the server (null until first page). */
  total: number | null;
  /** True while there are employees on the server that have not been loaded yet. */
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  error: ApiError | null;
  loadMore: () => void;
  retry: () => void;
}

/** Loads the employee directory one server page at a time. `GET /employees` is paginated
 * (max 100/page) and offers no search, so a picker built on only the first page silently makes
 * everyone after the first 100 unreachable. This hook never treats the first page as the whole
 * list: it exposes `total`/`hasMore` and an explicit `loadMore`, and loads nothing beyond what
 * the user asks for — memory stays bounded by user action, not by company size. */
export function useEmployeeDirectory({ enabled = true }: { enabled?: boolean } = {}): EmployeeDirectory {
  const beginRequest = useLatestRequest();
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [nextPage, setNextPage] = useState(1);
  const [totalPages, setTotalPages] = useState<number | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const inFlight = useRef(false);

  const loadPage = useCallback(
    async (page: number) => {
      if (inFlight.current) return;
      inFlight.current = true;
      const request = beginRequest();
      if (page === 1) setLoading(true);
      else setLoadingMore(true);
      setError(null);
      try {
        const { data, pagination } = await apiClient.getList<EmployeeOption>(
          "/employees",
          { page, per_page: EMPLOYEE_DIRECTORY_PAGE_SIZE },
          { signal: request.signal },
        );
        if (!request.isCurrent()) return;
        setEmployees((current) => {
          const known = new Set(current.map((e) => e.id));
          return page === 1 ? data : [...current, ...data.filter((e) => !known.has(e.id))];
        });
        setTotal(pagination?.total ?? null);
        // Without pagination metadata we cannot know there is more; offer no "load more".
        setTotalPages(pagination?.total_pages ?? page);
        setNextPage(page + 1);
      } catch (err) {
        if (isAbortError(err) || !request.isCurrent()) return;
        setError(
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        );
      } finally {
        inFlight.current = false;
        if (request.isCurrent()) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [beginRequest],
  );

  useEffect(() => {
    if (enabled) void loadPage(1);
  }, [enabled, loadPage]);

  const hasMore = totalPages !== null && nextPage <= totalPages;

  const loadMore = useCallback(() => {
    if (hasMore) void loadPage(nextPage);
  }, [hasMore, loadPage, nextPage]);

  const retry = useCallback(() => {
    void loadPage(employees.length === 0 ? 1 : nextPage);
  }, [employees.length, loadPage, nextPage]);

  return useMemo(
    () => ({ employees, total, hasMore, loading, loadingMore, error, loadMore, retry }),
    [employees, total, hasMore, loading, loadingMore, error, loadMore, retry],
  );
}
