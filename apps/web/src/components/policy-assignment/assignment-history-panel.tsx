import { Link2 } from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useMemo, useState } from "react";

import { BusyRegion } from "@/components/common/busy-region";
import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { PaginationControls } from "@/components/common/pagination-controls";
import {
  EndAssignmentDialog,
  type EndTarget,
} from "@/components/policy-assignment/end-assignment-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { TableSkeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableToolbar,
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
import {
  employeeOptionName,
  type EmployeeDirectory,
} from "@/lib/employee/use-employee-directory";
import {
  canEndAssignment,
  POLICY_KIND_LABELS,
  POLICY_KIND_LIST_PATH,
  POLICY_KINDS,
  SCOPE_TYPE_LABELS,
  SCOPE_TYPES,
  type PolicyAssignment,
  type PolicyKind,
  type ScopeType,
} from "@/lib/policy-assignment/types";

interface NamedOption {
  id: string;
  name?: string;
  title?: string;
}

type NameById = Record<string, string>;

function toNames(options: NamedOption[]): NameById {
  return Object.fromEntries(options.map((o) => [o.id, o.name ?? o.title ?? o.id]));
}

const SCOPE_PATHS = [
  "/legal-entities",
  "/branches",
  "/departments",
  "/grades",
  "/designations",
  "/shifts",
];

/** Every assignment, past and present, grouped by who it applies to within the page. */
export function AssignmentHistoryPanel({
  directory,
  today,
}: {
  directory: EmployeeDirectory;
  today: string;
}) {
  const [filterKind, setFilterKind] = useState<PolicyKind | "">("");
  const [filterScope, setFilterScope] = useState<ScopeType | "">("");
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const requestKey = `${filterKind}|${filterScope}|${page}|${refresh}`;
  const [result, setResult] = useState<{
    key: string;
    assignments: PolicyAssignment[] | null;
    pagination: PaginationMeta | null;
    error: ApiError | null;
  } | null>(null);

  const [policyNames, setPolicyNames] = useState<NameById>({});
  const [leaveTypeNames, setLeaveTypeNames] = useState<NameById>({});
  const [scopeNames, setScopeNames] = useState<NameById>({});
  const [ending, setEnding] = useState<EndTarget | null>(null);

  useEffect(() => {
    let current = true;
    apiClient
      .getList<PolicyAssignment>("/policy-assignments", {
        page,
        policy_kind: filterKind || undefined,
        scope_type: filterScope || undefined,
      })
      .then(({ data, pagination }) => {
        if (current) setResult({ key: requestKey, assignments: data, pagination, error: null });
      })
      .catch((err: unknown) => {
        if (!current) return;
        setResult({
          key: requestKey,
          assignments: null,
          pagination: null,
          error:
            err instanceof ApiError
              ? err
              : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        });
      });
    return () => {
      current = false;
    };
  }, [requestKey, filterKind, filterScope, page]);

  // Names include inactive policies and scopes that older rows still point at.
  useEffect(() => {
    const load = (path: string) =>
      apiClient.get<NamedOption[]>(path).catch(() => [] as NamedOption[]);
    void Promise.all(POLICY_KINDS.map((kind) => load(POLICY_KIND_LIST_PATH[kind]))).then((lists) =>
      setPolicyNames(toNames(lists.flat())),
    );
    void load("/leave-types").then((list) => setLeaveTypeNames(toNames(list)));
    void Promise.all(SCOPE_PATHS.map(load)).then((lists) => setScopeNames(toNames(lists.flat())));
  }, []);

  const employeeNames = useMemo(
    () => Object.fromEntries(directory.employees.map((e) => [e.id, employeeOptionName(e)])),
    [directory.employees],
  );

  const loading = result?.key !== requestKey;
  const assignments = result?.assignments ?? null;
  const error = !loading ? (result?.error ?? null) : null;

  function scopeLabel(a: PolicyAssignment): string {
    const label = SCOPE_TYPE_LABELS[a.scope_type];
    if (!a.scope_id) return label;
    if (a.scope_type === "EMPLOYEE") {
      return `${label}: ${employeeNames[a.scope_id] ?? "not in loaded list"}`;
    }
    return `${label}: ${scopeNames[a.scope_id] ?? "unavailable"}`;
  }

  const groups = useMemo(() => {
    const byScope = new Map<string, PolicyAssignment[]>();
    for (const a of assignments ?? []) {
      const key = `${a.scope_type}:${a.scope_id ?? ""}`;
      byScope.set(key, [...(byScope.get(key) ?? []), a]);
    }
    return [...byScope.entries()].sort(
      ([, x], [, y]) =>
        SCOPE_TYPES.indexOf(x[0].scope_type) - SCOPE_TYPES.indexOf(y[0].scope_type),
    );
  }, [assignments]);

  return (
    <TableContainer>
      <TableToolbar>
        <div className="grid w-full max-w-xl grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField id="filter-kind" label="Policy type">
            <NativeSelect
              value={filterKind}
              onChange={(e) => {
                setFilterKind(e.target.value as PolicyKind | "");
                setPage(1);
              }}
            >
              <option value="">All types</option>
              {POLICY_KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {POLICY_KIND_LABELS[kind]}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id="filter-scope" label="Applies to">
            <NativeSelect
              value={filterScope}
              onChange={(e) => {
                setFilterScope(e.target.value as ScopeType | "");
                setPage(1);
              }}
            >
              <option value="">Everyone</option>
              {SCOPE_TYPES.map((scope) => (
                <option key={scope} value={scope}>
                  {SCOPE_TYPE_LABELS[scope]}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>
      </TableToolbar>

      {loading && assignments === null ? (
        <div role="status" aria-label="Loading assignments">
          <TableSkeleton rows={8} columns={4} />
          <span className="sr-only">Loading assignments…</span>
        </div>
      ) : null}

      {error ? (
        <div className="p-6">
          <ErrorState
            message={
              error.status === 403
                ? "You do not have permission to view all policy assignments. Filter by a policy type you manage."
                : error.message
            }
            onRetry={() => setRefresh((n) => n + 1)}
          />
        </div>
      ) : null}

      {!error && assignments && assignments.length === 0 ? (
        <div className="p-6">
          <EmptyState
            icon={Link2}
            title="No policy assignments found."
            description="Use Set policies to choose what each group follows."
          />
        </div>
      ) : null}

      {!error && assignments && assignments.length > 0 ? (
        <BusyRegion busy={loading} label="Refreshing…">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Policy</TableHead>
                <TableHead>Effective range</TableHead>
                <TableHead>Status</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {groups.map(([key, rows]) => (
                <Fragment key={key}>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableCell colSpan={4} className="text-sm font-semibold text-foreground">
                      {scopeLabel(rows[0])}
                      {rows[0].scope_type === "EMPLOYEE" && rows[0].scope_id ? (
                        <Link
                          href={`/app/employees/${rows[0].scope_id}`}
                          className="ml-2 text-xs font-medium text-primary hover:underline"
                        >
                          Open profile
                        </Link>
                      ) : null}
                    </TableCell>
                  </TableRow>
                  {rows.map((a) => (
                    <TableRow key={a.id}>
                      <TableCell>
                        <p className="font-medium text-foreground">
                          {POLICY_KIND_LABELS[a.policy_kind]}
                          {a.leave_type_id
                            ? ` — ${leaveTypeNames[a.leave_type_id] ?? "Leave type unavailable"}`
                            : ""}
                        </p>
                        <p className="mt-0.5 text-xs text-foreground-muted">
                          {policyNames[a.policy_id] ?? "Policy name unavailable"}
                          {a.reason ? ` · ${a.reason}` : ""}
                        </p>
                      </TableCell>
                      <TableCell className="tabular-nums text-xs text-foreground-secondary">
                        <CompanyDate value={a.effective_from} /> –{" "}
                        {a.effective_to ? <CompanyDate value={a.effective_to} /> : "open"}
                      </TableCell>
                      <TableCell>
                        <Badge variant={a.effective_to === null ? "secondary" : "outline"}>
                          {a.effective_to === null ? "Current" : "Ended"}
                        </Badge>
                      </TableCell>
                      <TableCell align="right">
                        {canEndAssignment(a.policy_kind, a.scope_type, a.effective_to) ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              setEnding({
                                assignmentId: a.id,
                                version: a.version,
                                effectiveFrom: a.effective_from,
                                description: `${POLICY_KIND_LABELS[a.policy_kind]} for ${scopeLabel(a)}`,
                              })
                            }
                          >
                            End
                          </Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </BusyRegion>
      ) : null}

      {!error && result?.pagination ? (
        <PaginationControls pagination={result.pagination} onPageChange={setPage} disabled={loading} />
      ) : null}

      {ending ? (
        <EndAssignmentDialog
          key={ending.assignmentId}
          target={ending}
          today={today}
          onClose={() => setEnding(null)}
          onEnded={() => {
            setEnding(null);
            setRefresh((n) => n + 1);
          }}
        />
      ) : null}
    </TableContainer>
  );
}
