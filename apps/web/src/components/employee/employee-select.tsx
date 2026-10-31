"use client";

import { useId, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  employeeOptionName,
  type EmployeeDirectory,
} from "@/lib/employee/use-employee-directory";

interface EmployeeSelectProps {
  directory: EmployeeDirectory;
  value: string;
  onChange: (employeeId: string) => void;
  /** Label of the empty option, e.g. "Choose…" or "All employees". */
  emptyLabel?: string;
  /** Label for the currently selected employee when they are not in the loaded pages yet. */
  selectedLabel?: string;
  id?: string;
  disabled?: boolean;
  /** Employee to leave out of the options (e.g. an employee cannot be their own manager). */
  excludeId?: string;
  "aria-invalid"?: boolean;
}

/** Employee dropdown over a paginated directory. It never presents the loaded pages as the whole
 * company: when more employees exist on the server it says so ("Showing 100 of 342") and offers
 * "Load more". The filter box narrows only what is loaded, and says so — the employees API has no
 * server-side search. The current selection is always kept as an option, even if it lies beyond
 * the loaded pages, so loading more never silently clears a choice. */
export function EmployeeSelect({
  directory,
  value,
  onChange,
  emptyLabel = "Choose…",
  selectedLabel,
  id,
  disabled,
  excludeId,
  ...aria
}: EmployeeSelectProps) {
  const [query, setQuery] = useState("");
  const statusId = useId();
  const { employees, total, hasMore, loading, loadingMore, error } = directory;

  const options = useMemo(() => {
    const q = query.trim().toLowerCase();
    const candidates = excludeId ? employees.filter((e) => e.id !== excludeId) : employees;
    const matches = q
      ? candidates.filter((e) => employeeOptionName(e).toLowerCase().includes(q))
      : candidates;
    if (value && !matches.some((e) => e.id === value)) {
      const selected = employees.find((e) => e.id === value);
      return [
        selected ?? {
          id: value,
          first_name: selectedLabel ?? "Selected employee",
          last_name: null,
          employee_code: null,
        },
        ...matches,
      ];
    }
    return matches;
  }, [employees, query, value, selectedLabel, excludeId]);

  const showFilter = employees.length > 15 || hasMore;

  return (
    <div className="space-y-1.5">
      {showFilter ? (
        <Input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter loaded employees…"
          aria-label="Filter loaded employees"
          aria-describedby={statusId}
          disabled={disabled}
        />
      ) : null}
      <NativeSelect
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || (loading && employees.length === 0)}
        aria-describedby={statusId}
        {...aria}
      >
        <option value="">{loading && employees.length === 0 ? "Loading employees…" : emptyLabel}</option>
        {options.map((emp) => (
          <option key={emp.id} value={emp.id}>
            {employeeOptionName(emp)}
          </option>
        ))}
      </NativeSelect>
      <div id={statusId} className="flex flex-wrap items-center gap-2 text-xs text-foreground-muted">
        {error ? (
          <>
            <span role="alert" className="text-danger">
              Could not load employees.
            </span>
            <Button type="button" variant="ghost" size="xs" onClick={directory.retry}>
              Retry
            </Button>
          </>
        ) : hasMore ? (
          <>
            <span>
              Showing {employees.length} of {total ?? "many"} employees
              {query.trim() ? " (filter searches only these)" : ""}.
            </span>
            <Button
              type="button"
              variant="ghost"
              size="xs"
              onClick={directory.loadMore}
              disabled={loadingMore}
            >
              {loadingMore ? "Loading…" : "Load more"}
            </Button>
          </>
        ) : !loading && query.trim() && options.length === 0 ? (
          <span>No employee matches “{query.trim()}”.</span>
        ) : null}
      </div>
    </div>
  );
}
