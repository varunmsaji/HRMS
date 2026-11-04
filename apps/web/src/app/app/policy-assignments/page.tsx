"use client";

import { Link2, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { BusyRegion } from "@/components/common/busy-region";
import { PageHeader } from "@/components/common/page-header";
import { PaginationControls } from "@/components/common/pagination-controls";
import { EmployeeSelect } from "@/components/employee/employee-select";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
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
import { ChangeImpactDialog } from "@/components/work-calendar/change-impact-dialog";
import type { ProposedChange } from "@/lib/work-calendar/change-impact";
import { TableSkeleton } from "@/components/ui/skeleton";
import { isAbortError, useLatestRequest } from "@/hooks/use-latest-request";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { employeeOptionName, useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import {
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
  leave_type_id?: string;
  is_active?: boolean;
}

function optionLabel(option: NamedOption): string {
  return option.name ?? option.title ?? option.id;
}

const SCOPE_LIST_PATH: Partial<Record<ScopeType, string>> = {
  LEGAL_ENTITY: "/legal-entities",
  BRANCH: "/branches",
  DEPARTMENT: "/departments",
  GRADE: "/grades",
  DESIGNATION: "/designations",
  SHIFT: "/shifts",
};

interface CreateFormState {
  scopeType: ScopeType;
  scopeId: string;
  effectiveFrom: string;
  reason: string;
  /** Chosen policy id per row — keyed by `pickKey`; "" means "no change" (row skipped). */
  picks: Record<string, string>;
}

const EMPTY_FORM: CreateFormState = {
  scopeType: "COMPANY",
  scopeId: "",
  effectiveFrom: "",
  reason: "",
  picks: {},
};

/** Policy kinds that get a single row in the form. Leave policies get one row per leave type. */
const SINGLE_ROW_KINDS: PolicyKind[] = [
  "ATTENDANCE_POLICY",
  "OVERTIME_POLICY",
  "REGULARIZATION_POLICY",
  "WORK_CALENDAR",
  "WEEKLY_OFF",
];

/** Work Calendar / Weekly-Off changes go through the impact preview, one at a time. */
function needsImpactPreview(kind: PolicyKind): boolean {
  return kind === "WORK_CALENDAR" || kind === "WEEKLY_OFF";
}

/** The four versioned kinds can only be assigned once published; the API filters them. */
function assignableOptionsPath(kind: PolicyKind): string {
  return needsImpactPreview(kind)
    ? POLICY_KIND_LIST_PATH[kind]
    : `${POLICY_KIND_LIST_PATH[kind]}?assignable=true`;
}

/** Mirrors `end_policy_assignment`: the company-wide row is the safety net, and calendar kinds
 * change day classification so they can only be replaced through the impact preview. */
function canEndAssignment(assignment: PolicyAssignment): boolean {
  return (
    assignment.effective_to === null &&
    assignment.scope_type !== "COMPANY" &&
    !needsImpactPreview(assignment.policy_kind)
  );
}

type NameById = Record<string, string>;

function toNames(options: NamedOption[]): NameById {
  return Object.fromEntries(options.map((option) => [option.id, optionLabel(option)]));
}

/** The open assignment a new one would replace; the API needs its version to close it. Asked of
 * the server because the table only holds one filtered page. */
async function findOpenAssignment(
  kind: PolicyKind,
  scopeType: ScopeType,
  scopeId: string | null,
  leaveTypeId?: string,
): Promise<PolicyAssignment | null> {
  const { data } = await apiClient.getList<PolicyAssignment>("/policy-assignments", {
    policy_kind: kind,
    scope_type: scopeType,
    scope_id: scopeId ?? undefined,
    leave_type_id: leaveTypeId,
    current_only: "true",
  });
  return data[0] ?? null;
}

function pickKey(kind: PolicyKind, leaveTypeId?: string): string {
  return leaveTypeId ? `${kind}:${leaveTypeId}` : kind;
}

interface PickRow {
  key: string;
  kind: PolicyKind;
  leaveTypeId?: string;
  label: string;
  options: NamedOption[];
}

export default function PolicyAssignmentsPage() {
  const { toast } = useToast();
  const { user } = useAuth();
  const directory = useEmployeeDirectory();
  const [impact, setImpact] = useState<{
    change: ProposedChange;
    title: string;
    onDone: () => void | Promise<void>;
  } | null>(null);

  const [filterKind, setFilterKind] = useState<PolicyKind | "">("");
  const [assignments, setAssignments] = useState<PolicyAssignment[] | null>(null);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<CreateFormState>(EMPTY_FORM);
  const [policyOptionsByKind, setPolicyOptionsByKind] = useState<
    Partial<Record<PolicyKind, NamedOption[]>>
  >({});
  const [leaveTypeOptions, setLeaveTypeOptions] = useState<NamedOption[]>([]);
  const [scopeOptions, setScopeOptions] = useState<NamedOption[]>([]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [policyNames, setPolicyNames] = useState<NameById>({});
  const [leaveTypeNames, setLeaveTypeNames] = useState<NameById>({});
  const [scopeNames, setScopeNames] = useState<NameById>({});

  const [ending, setEnding] = useState<PolicyAssignment | null>(null);
  const [endDate, setEndDate] = useState("");
  const [endSaving, setEndSaving] = useState(false);
  const [endError, setEndError] = useState<string | null>(null);

  const employeeNames = useMemo(
    () => Object.fromEntries(directory.employees.map((e) => [e.id, employeeOptionName(e)])),
    [directory.employees],
  );

  const pickRows: PickRow[] = [
    ...SINGLE_ROW_KINDS.map((kind) => ({
      key: pickKey(kind),
      kind,
      label: POLICY_KIND_LABELS[kind],
      options: policyOptionsByKind[kind] ?? [],
    })),
    ...leaveTypeOptions.map((leaveType) => ({
      key: pickKey("LEAVE_POLICY", leaveType.id),
      kind: "LEAVE_POLICY" as PolicyKind,
      leaveTypeId: leaveType.id,
      label: `Leave Policy — ${optionLabel(leaveType)}`,
      options: (policyOptionsByKind.LEAVE_POLICY ?? []).filter(
        (option) => option.leave_type_id === leaveType.id,
      ),
    })),
  ];
  const chosenCount = pickRows.filter((row) => form.picks[row.key]).length;

  const beginRequest = useLatestRequest();

  const loadAssignments = useCallback(async (kind: PolicyKind | "", targetPage: number) => {
    const request = beginRequest();
    setLoading(true);
    setError(null);
    try {
      const { data, pagination: meta } = await apiClient.getList<PolicyAssignment>(
        "/policy-assignments",
        { page: targetPage, policy_kind: kind || undefined },
        { signal: request.signal },
      );
      if (!request.isCurrent()) return;
      setAssignments(data);
      setPagination(meta);
    } catch (err) {
      if (isAbortError(err) || !request.isCurrent()) return;
      setAssignments(null);
      setPagination(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      if (request.isCurrent()) setLoading(false);
    }
  }, [beginRequest]);

  useEffect(() => {
    setPage(1);
  }, [filterKind]);

  useEffect(() => {
    void loadAssignments(filterKind, page);
  }, [filterKind, page, loadAssignments]);

  // Names for the table: every policy and scope, including inactive ones older rows point at.
  useEffect(() => {
    const load = (path: string) => apiClient.get<NamedOption[]>(path).catch(() => [] as NamedOption[]);
    void Promise.all(POLICY_KINDS.map((kind) => load(POLICY_KIND_LIST_PATH[kind]))).then((lists) =>
      setPolicyNames(toNames(lists.flat())),
    );
    void load("/leave-types").then((list) => setLeaveTypeNames(toNames(list)));
    void Promise.all(Object.values(SCOPE_LIST_PATH).map(load)).then((lists) =>
      setScopeNames(toNames(lists.flat())),
    );
  }, []);

  useEffect(() => {
    if (!createOpen) return;
    void Promise.all([
      ...POLICY_KINDS.map((kind) =>
        apiClient
          .get<NamedOption[]>(assignableOptionsPath(kind))
          .then((options) => options.filter((option) => option.is_active !== false))
          .catch(() => [] as NamedOption[]),
      ),
      apiClient.get<NamedOption[]>("/leave-types").catch(() => [] as NamedOption[]),
    ]).then((results) => {
      const byKind: Partial<Record<PolicyKind, NamedOption[]>> = {};
      POLICY_KINDS.forEach((kind, index) => {
        byKind[kind] = results[index];
      });
      setPolicyOptionsByKind(byKind);
      setLeaveTypeOptions(results[POLICY_KINDS.length]);
    });
  }, [createOpen]);

  useEffect(() => {
    if (!createOpen) return;
    const path = SCOPE_LIST_PATH[form.scopeType];
    if (!path) {
      setScopeOptions([]);
      return;
    }
    void apiClient
      .get<NamedOption[]>(path)
      .then(setScopeOptions)
      .catch(() => setScopeOptions([]));
  }, [createOpen, form.scopeType]);

  function openCreate() {
    setForm(EMPTY_FORM);
    setFormError(null);
    setCreateOpen(true);
  }

  async function finishCreate(count: number) {
    setCreateOpen(false);
    toast({
      title: count === 1 ? "Assignment created" : `${count} assignments created`,
      variant: "success",
    });
    await loadAssignments(filterKind, page);
  }

  /** Work Calendar / Weekly-Off rows: each one is previewed and confirmed before it is applied. */
  async function runImpactQueue(
    rows: PickRow[],
    base: Record<string, unknown>,
    createdSoFar: number,
  ) {
    const [row, ...rest] = rows;
    if (!row) {
      void finishCreate(createdSoFar);
      return;
    }
    const body = { ...base, policy_kind: row.kind, policy_id: form.picks[row.key] };
    let current: PolicyAssignment | null;
    try {
      current = await findOpenAssignment(
        row.kind,
        form.scopeType,
        form.scopeType === "COMPANY" ? null : form.scopeId,
      );
    } catch (err) {
      setFormError(`${row.label}: ${describeApiError(err)}`);
      return;
    }
    setImpact({
      change: { change_type: "ASSIGNMENT_CREATE", body, expected_version: current?.version },
      title: `Create assignment — ${row.label}`,
      onDone: () => {
        setForm((f) => ({ ...f, picks: { ...f.picks, [row.key]: "" } }));
        void runImpactQueue(rest, base, createdSoFar + 1);
      },
    });
  }

  async function handleCreate() {
    const chosen = pickRows.filter((row) => form.picks[row.key]);
    if (chosen.length === 0) {
      setFormError("Choose at least one policy to assign.");
      return;
    }
    if (form.scopeType !== "COMPANY" && !form.scopeId) {
      setFormError("Choose or enter a scope target.");
      return;
    }
    if (!form.effectiveFrom) {
      setFormError("Effective from is required.");
      return;
    }
    const scopeId = form.scopeType === "COMPANY" ? null : form.scopeId;
    const base = {
      scope_type: form.scopeType,
      scope_id: scopeId,
      effective_from: form.effectiveFrom,
      reason: form.reason.trim() || null,
    };

    setSaving(true);
    setFormError(null);
    const remainingPicks = { ...form.picks };
    const failures: string[] = [];
    let created = 0;
    for (const row of chosen.filter((r) => !needsImpactPreview(r.kind))) {
      try {
        const open = await findOpenAssignment(row.kind, form.scopeType, scopeId, row.leaveTypeId);
        await apiClient.post<PolicyAssignment>(
          "/policy-assignments",
          {
            ...base,
            policy_kind: row.kind,
            policy_id: form.picks[row.key],
            leave_type_id: row.leaveTypeId,
          },
          open ? { ifMatch: String(open.version) } : undefined,
        );
        created += 1;
        remainingPicks[row.key] = "";
      } catch (err) {
        failures.push(`${row.label}: ${describeApiError(err)}`);
      }
    }
    setSaving(false);
    setForm((f) => ({ ...f, picks: remainingPicks }));
    if (created > 0) await loadAssignments(filterKind, page);

    if (failures.length > 0) {
      setFormError(
        `${created} created, ${failures.length} failed — fix and try again:\n${failures.join("\n")}`,
      );
      return;
    }
    await runImpactQueue(
      chosen.filter((r) => needsImpactPreview(r.kind)),
      base,
      created,
    );
  }

  function openEnd(assignment: PolicyAssignment) {
    const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
    setEnding(assignment);
    setEndDate(today < assignment.effective_from ? assignment.effective_from : today);
    setEndError(null);
  }

  async function handleEnd() {
    if (!ending) return;
    if (!endDate) {
      setEndError("Last day is required.");
      return;
    }
    setEndSaving(true);
    setEndError(null);
    try {
      await apiClient.post<PolicyAssignment>(
        `/policy-assignments/${ending.id}/end`,
        { effective_to: endDate },
        { ifMatch: String(ending.version) },
      );
      setEnding(null);
      toast({ title: "Assignment ended", variant: "success" });
      await loadAssignments(filterKind, page);
    } catch (err) {
      setEndError(describeApiError(err));
    } finally {
      setEndSaving(false);
    }
  }

  function scopeLabel(assignment: PolicyAssignment): string {
    const label = SCOPE_TYPE_LABELS[assignment.scope_type];
    if (!assignment.scope_id) return label;
    if (assignment.scope_type === "EMPLOYEE") {
      return `${label}: ${employeeNames[assignment.scope_id] ?? "not in loaded list"}`;
    }
    return `${label}: ${scopeNames[assignment.scope_id] ?? "unavailable"}`;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title="Policy Assignments"
        description="Assign a Work Calendar, Weekly-Off Pattern, Attendance/Overtime/Regularization/Leave Policy to a scope. Most specific wins: EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT > BRANCH > LEGAL_ENTITY > COMPANY."
        actions={
          <Button type="button" onClick={openCreate}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            New Assignment
          </Button>
        }
      />

      <TableContainer>
        <TableToolbar>
          <div className="w-full max-w-xs">
            <FormField id="filter-kind" label="Filter by policy kind">
              <NativeSelect
                value={filterKind}
                onChange={(e) => setFilterKind(e.target.value as PolicyKind | "")}
              >
                <option value="">All kinds</option>
                {POLICY_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {POLICY_KIND_LABELS[kind]}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          </div>
        </TableToolbar>

        {loading && assignments === null ? (
          <div role="status" aria-label="Loading assignments">
            <TableSkeleton rows={8} columns={5} />
            <span className="sr-only">Loading assignments…</span>
          </div>
        ) : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view policy assignments."
                  : error.message
              }
              onRetry={() => void loadAssignments(filterKind, page)}
            />
          </div>
        ) : null}

        {!error && assignments && assignments.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={Link2}
              title="No policy assignments yet."
              description="Assign a policy to a scope so employees can resolve it."
              action={
                <Button type="button" onClick={openCreate}>
                  New Assignment
                </Button>
              }
            />
          </div>
        ) : null}

        {!error && assignments && assignments.length > 0 ? (
          <BusyRegion busy={loading} label="Refreshing…">
<Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Policy &amp; Scope</TableHead>
                <TableHead>Effective Range</TableHead>
                <TableHead>Status</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {assignments.map((a) => (
                <TableRow key={a.id}>
                  <TableCell>
                    <p className="font-medium text-foreground">
                      {POLICY_KIND_LABELS[a.policy_kind]} → {scopeLabel(a)}
                    </p>
                    <p className="mt-0.5 text-xs text-foreground-muted">
                      {policyNames[a.policy_id] ?? "Policy name unavailable"}
                      {a.leave_type_id
                        ? ` · ${leaveTypeNames[a.leave_type_id] ?? "Leave type unavailable"}`
                        : ""}
                      {a.reason ? ` · ${a.reason}` : ""}
                      {a.scope_type === "EMPLOYEE" && a.scope_id ? (
                        <>
                          {" · "}
                          <Link
                            href={`/app/employees/${a.scope_id}`}
                            className="text-primary hover:underline"
                          >
                            Open profile
                          </Link>
                        </>
                      ) : null}
                    </p>
                  </TableCell>
                  <TableCell className="tabular-nums text-xs text-foreground-secondary">
                    <CompanyDate value={a.effective_from} /> –{" "}
                    {a.effective_to ? <CompanyDate value={a.effective_to} /> : "open"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={a.effective_to === null ? "secondary" : "outline"}>
                      {a.effective_to === null ? (
                        "Current"
                      ) : (
                        <>
                          Ended <CompanyDate value={a.effective_to} />
                        </>
                      )}
                    </Badge>
                  </TableCell>
                  <TableCell align="right">
                    {canEndAssignment(a) ? (
                      <Button type="button" variant="outline" size="sm" onClick={() => openEnd(a)}>
                        End
                      </Button>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
</BusyRegion>
        ) : null}

        {!error && pagination ? (
          <PaginationControls
            pagination={pagination}
            onPageChange={setPage}
            disabled={loading}
          />
        ) : null}
      </TableContainer>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>New Policy Assignment</DialogTitle>
          </DialogHeader>
          <div className="max-h-[65vh] space-y-4 overflow-y-auto pr-1">
            <FormField id="assign-scope-type" label="Who does this apply to? (scope)" required>
              <NativeSelect
                value={form.scopeType}
                onChange={(e) =>
                  setForm((f) => ({ ...f, scopeType: e.target.value as ScopeType, scopeId: "" }))
                }
              >
                {SCOPE_TYPES.map((scope) => (
                  <option key={scope} value={scope}>
                    {SCOPE_TYPE_LABELS[scope]}
                  </option>
                ))}
              </NativeSelect>
            </FormField>

            {form.scopeType !== "COMPANY" && SCOPE_LIST_PATH[form.scopeType] ? (
              <FormField id="assign-scope-id" label={SCOPE_TYPE_LABELS[form.scopeType]} required>
                <NativeSelect
                  value={form.scopeId}
                  onChange={(e) => setForm((f) => ({ ...f, scopeId: e.target.value }))}
                >
                  <option value="">Choose…</option>
                  {scopeOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {optionLabel(option)}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
            ) : null}

            {form.scopeType === "EMPLOYEE" ? (
              <FormField id="assign-employee-id" label="Employee" required>
                <EmployeeSelect
                  directory={directory}
                  value={form.scopeId}
                  onChange={(scopeId) => setForm((f) => ({ ...f, scopeId }))}
                />
              </FormField>
            ) : null}

            <FormField id="assign-effective-from" label="Effective from" required>
              <Input
                type="date"
                value={form.effectiveFrom}
                onChange={(e) => setForm((f) => ({ ...f, effectiveFrom: e.target.value }))}
              />
            </FormField>

            <section className="space-y-3">
              <div>
                <h3 className="text-sm font-medium text-foreground">Policies to assign</h3>
                <p className="text-xs text-foreground-muted">
                  Pick a policy for each kind you want to assign. Rows left on &quot;No change&quot;
                  are skipped. A group follows one policy of each kind, so a new one replaces the
                  current one from the effective date. Only active, published policies are listed.
                </p>
              </div>
              {pickRows.map((row) => (
                <FormField
                  key={row.key}
                  id={`assign-pick-${row.key}`}
                  label={row.label}
                  description={row.options.length === 0 ? "Nothing to assign yet." : undefined}
                >
                  <NativeSelect
                    value={form.picks[row.key] ?? ""}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, picks: { ...f.picks, [row.key]: e.target.value } }))
                    }
                  >
                    <option value="">No change</option>
                    {row.options.map((option) => (
                      <option key={option.id} value={option.id}>
                        {optionLabel(option)}
                      </option>
                    ))}
                  </NativeSelect>
                </FormField>
              ))}
            </section>

            <FormField id="assign-reason" label="Reason (optional)">
              <Input
                value={form.reason}
                onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
              />
            </FormField>

            {formError ? (
              <p className="whitespace-pre-line text-sm text-danger">{formError}</p>
            ) : null}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setCreateOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handleCreate()}
              disabled={saving || chosenCount === 0}
            >
              {saving
                ? "Creating…"
                : chosenCount > 1
                  ? `Create ${chosenCount} assignments`
                  : "Create assignment"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={ending !== null} onOpenChange={(open) => (!open && !endSaving ? setEnding(null) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>End this assignment?</DialogTitle>
            <DialogDescription>
              {ending
                ? `${POLICY_KIND_LABELS[ending.policy_kind]} for ${scopeLabel(ending)}. After the last day, these people follow the next wider assignment, ending at the company-wide one.`
                : null}
            </DialogDescription>
          </DialogHeader>
          <FormField id="end-assignment-date" label="Last day" required>
            <Input
              type="date"
              min={ending?.effective_from}
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </FormField>
          {endError ? <p className="text-sm text-danger">{endError}</p> : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setEnding(null)} disabled={endSaving}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void handleEnd()}
              disabled={endSaving}
            >
              {endSaving ? "Ending…" : "End assignment"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ChangeImpactDialog
        change={impact?.change ?? null}
        title={impact?.title ?? ""}
        onClose={() => setImpact(null)}
        onApplied={() => {
          const done = impact?.onDone;
          setImpact(null);
          void done?.();
        }}
      />
    </div>
  );
}
