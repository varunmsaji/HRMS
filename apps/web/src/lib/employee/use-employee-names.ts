"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { apiClient } from "@/lib/api/client";
import { employeeOptionName, type EmployeeOption } from "@/lib/employee/use-employee-directory";

const MAX_CONCURRENT_LOOKUPS = 4;

/** Resolves employee ids (taken from rows already on screen) to display names.
 *
 * Names already present in `known` (e.g. a loaded directory page) are used directly; any other id
 * is fetched once with `GET /employees/{id}` — the API has no batch lookup. Before this, a name
 * column built from a first-page-only directory showed a raw UUID for everyone else. The
 * cache lives in this hook instance, so it is dropped with the page and can never leak names across
 * users or tenants. Ids the caller may not see (403/404) resolve to `null` and are not retried. */
const NO_KNOWN_EMPLOYEES: EmployeeOption[] = [];

export function useEmployeeNames(ids: string[], known: EmployeeOption[] = NO_KNOWN_EMPLOYEES) {
  const [fetched, setFetched] = useState<Map<string, string | null>>(() => new Map());
  const requested = useRef<Set<string>>(new Set());

  const knownById = useMemo(() => new Map(known.map((e) => [e.id, e])), [known]);
  const idKey = useMemo(() => [...new Set(ids)].sort().join(","), [ids]);

  useEffect(() => {
    const requestedIds = requested.current;
    const missing = idKey
      .split(",")
      .filter((id) => id && !knownById.has(id) && !requestedIds.has(id));
    if (missing.length === 0) return;
    missing.forEach((id) => requestedIds.add(id));

    let cancelled = false;
    const queue = [...missing];
    async function worker() {
      while (queue.length > 0 && !cancelled) {
        const id = queue.shift() as string;
        let name: string | null = null;
        try {
          name = employeeOptionName(await apiClient.get<EmployeeOption>(`/employees/${id}`));
        } catch {
          name = null;
        }
        if (!cancelled) setFetched((current) => new Map(current).set(id, name));
      }
    }
    void Promise.all(Array.from({ length: Math.min(MAX_CONCURRENT_LOOKUPS, queue.length) }, worker));
    return () => {
      cancelled = true;
      // A cancelled lookup was not answered: allow it to be requested again.
      missing.forEach((id) => {
        if (!queue.includes(id)) return;
        requestedIds.delete(id);
      });
    };
  }, [idKey, knownById]);

  return useMemo(
    () => (id: string): string => {
      const option = knownById.get(id);
      if (option) return employeeOptionName(option);
      const name = fetched.get(id);
      if (name) return name;
      return name === null ? "Unavailable employee" : "Loading…";
    },
    [knownById, fetched],
  );
}
