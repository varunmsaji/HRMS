"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import type { LeaveBalance } from "@/lib/leave-ledger/types";

export type TeamBalanceRow =
  | { status: "loading" }
  | { status: "ready"; balances: LeaveBalance[] }
  | { status: "error"; message: string; forbidden: boolean };

const LOADING: TeamBalanceRow = { status: "loading" };

export interface TeamBalances {
  /** The current state for an employee; anything not requested yet reads as loading. */
  rowFor: (employeeId: string) => TeamBalanceRow;
  /** Every row that finished loading, in no particular order. */
  readyRows: LeaveBalance[][];
  retry: (employeeId: string) => void;
}

/** Balances for a set of employees, fetched through the single-employee `GET /leave-balances`
 * (the API has no "everyone" list). Each employee is fetched at most once and cached, at most
 * `concurrency` requests run at a time, and nothing is aborted when the visible set changes — a
 * request started for a page the user has just left still fills the cache for when they return.
 * Not abort-on-cleanup on purpose: StrictMode's mount/unmount/mount would cancel the first
 * request while the second skipped it as "already requested". */
export function useTeamBalances(employeeIds: readonly string[], concurrency = 4): TeamBalances {
  const [rows, setRows] = useState<Record<string, TeamBalanceRow>>({});
  const requested = useRef(new Set<string>());
  const queue = useRef<string[]>([]);
  const active = useRef(0);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const pump = useCallback(() => {
    function run(): void {
      while (active.current < concurrency && queue.current.length > 0) {
        const id = queue.current.shift() as string;
        active.current += 1;
        apiClient
          .get<LeaveBalance[]>(`/leave-balances?employee_id=${id}`)
          .then((balances) => {
            if (mounted.current) setRows((r) => ({ ...r, [id]: { status: "ready", balances } }));
          })
          .catch((err: unknown) => {
            if (!mounted.current) return;
            const forbidden = err instanceof ApiError && err.status === 403;
            setRows((r) => ({
              ...r,
              [id]: {
                status: "error",
                forbidden,
                message: forbidden ? "No access" : describeApiError(err),
              },
            }));
          })
          .finally(() => {
            active.current -= 1;
            run();
          });
      }
    }
    run();
  }, [concurrency]);

  const key = employeeIds.join("|");
  useEffect(() => {
    for (const id of key ? key.split("|") : []) {
      if (!requested.current.has(id)) {
        requested.current.add(id);
        queue.current.push(id);
      }
    }
    pump();
  }, [key, pump]);

  const retry = useCallback(
    (employeeId: string) => {
      setRows(({ [employeeId]: _dropped, ...rest }) => rest);
      requested.current.add(employeeId);
      queue.current.push(employeeId);
      pump();
    },
    [pump],
  );

  const rowFor = useCallback((employeeId: string) => rows[employeeId] ?? LOADING, [rows]);
  const readyRows = Object.values(rows).flatMap((r) => (r.status === "ready" ? [r.balances] : []));

  return { rowFor, readyRows, retry };
}
