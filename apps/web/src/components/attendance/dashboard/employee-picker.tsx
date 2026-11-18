"use client";

import { Search, X } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { Input } from "@/components/ui/input";
import { employeeName, type EmployeeLite } from "@/lib/attendance/dashboard";
import { cn } from "@/lib/utils";

const MAX_RESULTS = 8;

interface EmployeePickerProps {
  id: string;
  employees: EmployeeLite[];
  /** The chosen employee's id, or "" for everyone. */
  value: string;
  onChange: (employeeId: string) => void;
  className?: string;
}

/** Type-to-find replacement for a native select that lists every employee. Matches name or
 * employee code; shows the first few matches, so it stays usable with hundreds of people. Once
 * someone is chosen the box becomes a pill with a clear button. */
export function EmployeePicker({ id, employees, value, onChange, className }: EmployeePickerProps) {
  const listId = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  const selected = value ? employees.find((e) => e.id === value) : undefined;

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const named = employees.map((employee) => ({ employee, name: employeeName(employee, employee.id) }));
    const hits = q
      ? named.filter(({ employee, name }) => name.toLowerCase().includes(q) || (employee.employee_code ?? "").toLowerCase().includes(q))
      : named;
    return hits.sort((a, b) => a.name.localeCompare(b.name)).slice(0, MAX_RESULTS);
  }, [employees, query]);

  function choose(employeeId: string) {
    onChange(employeeId);
    setQuery("");
    setOpen(false);
    setActive(0);
  }

  if (value) {
    const label = selected ? employeeName(selected, selected.id) : "Selected employee";
    return (
      <div className={cn("flex h-9 w-full items-center justify-between gap-2 rounded-md border border-primary bg-primary-subtle/40 px-3 text-sm", className)}>
        <span className="truncate font-medium text-foreground" id={id}>
          {label}
          {selected?.employee_code ? <span className="ml-1.5 font-normal text-foreground-muted">{selected.employee_code}</span> : null}
        </span>
        <button
          type="button"
          aria-label={`Clear employee ${label}`}
          onClick={() => choose("")}
          className="shrink-0 rounded p-0.5 text-foreground-muted hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>
    );
  }

  return (
    <div className={cn("relative w-full", className)}>
      <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-foreground-muted" aria-hidden="true" />
      <Input
        id={id}
        type="text"
        role="combobox"
        aria-label="Employee"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && matches[active] ? `${listId}-${matches[active].employee.id}` : undefined}
        autoComplete="off"
        placeholder="Find employee…"
        className="pl-8"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
            setActive((i) => Math.min(i + 1, Math.max(matches.length - 1, 0)));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((i) => Math.max(i - 1, 0));
          } else if (e.key === "Enter" && open && matches[active]) {
            e.preventDefault();
            choose(matches[active].employee.id);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {open ? (
        <ul
          id={listId}
          role="listbox"
          aria-label="Employees"
          className="absolute z-20 mt-1 max-h-64 w-full min-w-[14rem] overflow-auto rounded-md border border-border bg-surface py-1 shadow-elevation-2"
        >
          {matches.length === 0 ? (
            <li className="px-3 py-2 text-sm text-foreground-muted">No employee matches “{query.trim()}”.</li>
          ) : (
            matches.map(({ employee, name }, index) => (
              <li
                key={employee.id}
                id={`${listId}-${employee.id}`}
                role="option"
                aria-selected={index === active}
                // mousedown, not click: the input's blur would close the list before a click lands.
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(employee.id);
                }}
                onMouseEnter={() => setActive(index)}
                className={cn("flex cursor-pointer items-baseline justify-between gap-3 px-3 py-1.5 text-sm", index === active && "bg-muted")}
              >
                <span className="truncate text-foreground">{name}</span>
                {employee.employee_code ? <span className="shrink-0 text-xs text-foreground-muted">{employee.employee_code}</span> : null}
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}
