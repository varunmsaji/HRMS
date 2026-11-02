"use client";

import { ChevronRight, Search, Users } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { PaginationControls } from "@/components/common/pagination-controls";
import { EmployeeAvatar } from "@/components/employee/employee-identity";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton, TableSkeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
  TableToolbar,
} from "@/components/ui/table";
import {
  employeeOptionName,
  type EmployeeDirectory,
  type EmployeeOption,
} from "@/lib/employee/use-employee-directory";
import {
  balanceTone,
  collectLeaveTypes,
  filterEmployees,
  formatDays,
  hasAmount,
  pageSlice,
  type LeaveTypeColumn,
} from "@/lib/leave-ledger/matrix";
import type { LeaveBalance } from "@/lib/leave-ledger/types";
import { useTeamBalances, type TeamBalanceRow } from "@/lib/leave-ledger/use-team-balances";
import { cn } from "@/lib/utils";

export const MATRIX_PAGE_SIZE = 20;

interface TeamBalanceMatrixProps {
  directory: EmployeeDirectory;
  onSelectEmployee: (employeeId: string) => void;
}

/** Everyone's leave balances at a glance: a row per employee, a column per leave type. Opening a
 * row hands off to the per-employee ledger. Only the visible page's balances are fetched. */
export function TeamBalanceMatrix({ directory, onSelectEmployee }: TeamBalanceMatrixProps) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);

  const filtered = useMemo(() => filterEmployees(directory.employees, query), [directory.employees, query]);
  const slice = pageSlice(filtered, page, MATRIX_PAGE_SIZE);
  const visibleIds = useMemo(() => slice.rows.map((e) => e.id), [slice.rows]);

  const balances = useTeamBalances(visibleIds);
  const columns = useMemo(() => collectLeaveTypes(balances.readyRows), [balances.readyRows]);

  if (directory.loading && directory.employees.length === 0) {
    return (
      <TableContainer>
        <div role="status" aria-label="Loading employees">
          <TableSkeleton rows={8} columns={5} />
          <span className="sr-only">Loading employees…</span>
        </div>
      </TableContainer>
    );
  }

  if (directory.error && directory.employees.length === 0) {
    return <ErrorState message="Could not load employees." onRetry={directory.retry} />;
  }

  if (directory.employees.length === 0) {
    return <EmptyState icon={Users} title="No employees yet." description="Balances appear once employees are added." />;
  }

  const loadedLabel = directory.hasMore
    ? `Showing the first ${directory.employees.length} of ${directory.total ?? "many"} employees`
    : `${filtered.length} ${filtered.length === 1 ? "employee" : "employees"}`;

  return (
    <TableContainer>
      <TableToolbar>
        <div>
          <h2 className="text-sm font-semibold text-foreground">Leave balances by employee</h2>
          <p className="mt-0.5 text-xs text-foreground-muted" aria-live="polite">
            {loadedLabel}
            {directory.hasMore ? (
              <Button
                type="button"
                variant="ghost"
                size="xs"
                className="ml-1 text-primary"
                onClick={directory.loadMore}
                disabled={directory.loadingMore}
              >
                {directory.loadingMore ? "Loading…" : "Load more"}
              </Button>
            ) : null}
          </p>
        </div>
        <div className="relative w-full max-w-xs">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted"
            aria-hidden="true"
          />
          <Input
            type="search"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            placeholder="Find by name or code…"
            aria-label="Find an employee"
            className="pl-9"
          />
        </div>
      </TableToolbar>

      {slice.rows.length === 0 ? (
        <div className="p-6">
          <EmptyState
            icon={Search}
            title="No employee matches your search."
            action={
              <Button type="button" variant="outline" size="sm" onClick={() => setQuery("")}>
                Clear search
              </Button>
            }
          />
        </div>
      ) : (
        <Table aria-label="Leave balances by employee">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Employee</TableHead>
              {columns.map((c) => (
                <TableHead key={c.id} align="right" title={c.name}>
                  {c.name}
                </TableHead>
              ))}
              {columns.length === 0 ? <TableHead align="right">Balances</TableHead> : null}
              <TableHead align="right">
                <span className="sr-only">Open</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {slice.rows.map((employee) => (
              <MatrixRow
                key={employee.id}
                employee={employee}
                columns={columns}
                row={balances.rowFor(employee.id)}
                onOpen={() => onSelectEmployee(employee.id)}
                onRetry={() => balances.retry(employee.id)}
              />
            ))}
          </TableBody>
        </Table>
      )}

      <PaginationControls
        pagination={{ page: slice.page, per_page: MATRIX_PAGE_SIZE, total: slice.total, total_pages: slice.totalPages }}
        onPageChange={setPage}
      />
    </TableContainer>
  );
}

function MatrixRow({
  employee,
  columns,
  row,
  onOpen,
  onRetry,
}: {
  employee: EmployeeOption;
  columns: LeaveTypeColumn[];
  row: TeamBalanceRow;
  onOpen: () => void;
  onRetry: () => void;
}) {
  const name = employeeOptionName({ ...employee, employee_code: null });
  const colSpan = Math.max(columns.length, 1);

  return (
    <TableRow>
      <TableCell nowrap>
        <button
          type="button"
          onClick={onOpen}
          aria-label={`Open ${name}'s leave ledger`}
          className="flex items-center gap-2.5 rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <EmployeeAvatar name={name} code={employee.employee_code} size="md" />
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium text-foreground">{name}</span>
            {employee.employee_code ? (
              <span className="block font-mono text-2xs text-foreground-muted">{employee.employee_code}</span>
            ) : null}
          </span>
        </button>
      </TableCell>

      {row.status === "ready" ? (
        columns.length === 0 ? (
          <TableCell align="right" className="text-foreground-muted">
            No balance-backed leave types
          </TableCell>
        ) : (
          columns.map((c) => <BalanceCell key={c.id} balance={row.balances.find((b) => b.leave_type_id === c.id)} />)
        )
      ) : row.status === "error" ? (
        <TableCell align="right" colSpan={colSpan}>
          <span className="text-xs text-danger">{row.message}</span>
          {row.forbidden ? null : (
            <Button type="button" variant="ghost" size="xs" className="ml-1 text-primary" onClick={onRetry}>
              Retry
            </Button>
          )}
        </TableCell>
      ) : (
        Array.from({ length: colSpan }, (_, i) => (
          <TableCell key={i} align="right">
            <Skeleton className="ml-auto h-4 w-8" aria-hidden="true" />
          </TableCell>
        ))
      )}

      <TableCell align="right" nowrap>
        <Button type="button" variant="ghost" size="xs" className="text-primary" onClick={onOpen} tabIndex={-1} aria-hidden="true">
          View
          <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Button>
      </TableCell>
    </TableRow>
  );
}

function BalanceCell({ balance }: { balance: LeaveBalance | undefined }) {
  if (!balance) {
    return (
      <TableCell align="right" numeric>
        <TableEmpty label="Not applicable" />
      </TableCell>
    );
  }
  const tone = balanceTone(balance.balance);
  return (
    <TableCell align="right" numeric nowrap>
      <span
        className={cn(
          "text-sm font-semibold",
          tone === "negative" && "text-danger",
          tone === "zero" && "font-medium text-foreground-muted",
          tone === "positive" && "text-foreground",
        )}
      >
        {formatDays(balance.balance)}
      </span>
      {hasAmount(balance.reserved_balance) ? (
        <span className="block text-2xs font-normal text-warning">{formatDays(balance.reserved_balance)} pending</span>
      ) : null}
    </TableCell>
  );
}
