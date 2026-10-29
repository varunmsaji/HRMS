"use client";

import { Link2, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { PaginationControls } from "@/components/common/pagination-controls";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
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
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
import {
  POLICY_KIND_LABELS,
  POLICY_KIND_LIST_PATH,
  POLICY_KINDS,
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
  policyKind: PolicyKind;
  policyId: string;
  leaveTypeId: string;
  scopeType: ScopeType;
  scopeId: string;
  effectiveFrom: string;
  reason: string;
}

const EMPTY_FORM: CreateFormState = {
  policyKind: "ATTENDANCE_POLICY",
  policyId: "",
  leaveTypeId: "",
  scopeType: "COMPANY",
  scopeId: "",
  effectiveFrom: "",
  reason: "",
};

export default function PolicyAssignmentsPage() {
  const { toast } = useToast();
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
  const [policyOptions, setPolicyOptions] = useState<NamedOption[]>([]);
  const [leaveTypeOptions, setLeaveTypeOptions] = useState<NamedOption[]>([]);
  const [scopeOptions, setScopeOptions] = useState<NamedOption[]>([]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const isLeavePolicy = form.policyKind === "LEAVE_POLICY";
  const visiblePolicyOptions = isLeavePolicy
    ? policyOptions.filter((option) => option.leave_type_id === form.leaveTypeId)
    : policyOptions;

  const loadAssignments = useCallback(async (kind: PolicyKind | "", targetPage: number) => {
    setLoading(true);
    setError(null);
    try {
      const { data, pagination: meta } = await apiClient.getList<PolicyAssignment>(
        "/policy-assignments",
        { page: targetPage, policy_kind: kind || undefined },
      );
      setAssignments(data);
      setPagination(meta);
    } catch (err) {
      setAssignments(null);
      setPagination(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setPage(1);
  }, [filterKind]);

  useEffect(() => {
    void loadAssignments(filterKind, page);
  }, [filterKind, page, loadAssignments]);

  useEffect(() => {
    if (!createOpen) return;
    void apiClient
      .get<NamedOption[]>(POLICY_KIND_LIST_PATH[form.policyKind])
      .then(setPolicyOptions)
      .catch(() => setPolicyOptions([]));
  }, [createOpen, form.policyKind]);

  useEffect(() => {
    if (!createOpen || !isLeavePolicy) return;
    void apiClient
      .get<NamedOption[]>("/leave-types")
      .then(setLeaveTypeOptions)
      .catch(() => setLeaveTypeOptions([]));
  }, [createOpen, isLeavePolicy]);

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

  async function handleCreate() {
    if (isLeavePolicy && !form.leaveTypeId) {
      setFormError("Choose which leave type this policy is for.");
      return;
    }
    if (!form.policyId) {
      setFormError("Choose which policy to assign.");
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
    const payload = {
      policy_kind: form.policyKind,
      policy_id: form.policyId,
      leave_type_id: isLeavePolicy ? form.leaveTypeId : undefined,
      scope_type: form.scopeType,
      scope_id: form.scopeType === "COMPANY" ? null : form.scopeId,
      effective_from: form.effectiveFrom,
      reason: form.reason.trim() || null,
    };
    if (form.policyKind === "WORK_CALENDAR" || form.policyKind === "WEEKLY_OFF") {
      const current = (assignments ?? []).find(
        (a) =>
          a.policy_kind === form.policyKind &&
          a.scope_type === form.scopeType &&
          (a.scope_id ?? null) === payload.scope_id &&
          a.effective_to === null,
      );
      setFormError(null);
      setImpact({
        change: {
          change_type: "ASSIGNMENT_CREATE",
          body: payload,
          expected_version: current?.version,
        },
        title: "Create assignment",
        onDone: async () => {
          setCreateOpen(false);
          toast({ title: "Assignment created", variant: "success" });
          await loadAssignments(filterKind, page);
        },
      });
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await apiClient.post<PolicyAssignment>("/policy-assignments", {
        policy_kind: form.policyKind,
        policy_id: form.policyId,
        leave_type_id: isLeavePolicy ? form.leaveTypeId : undefined,
        scope_type: form.scopeType,
        scope_id: form.scopeType === "COMPANY" ? null : form.scopeId,
        effective_from: form.effectiveFrom,
        reason: form.reason.trim() || null,
      });
      setCreateOpen(false);
      toast({ title: "Assignment created", variant: "success" });
      await loadAssignments(filterKind, page);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 422 || err.status === 409)) {
        setFormError(describeApiError(err));
        return;
      }
      toast({
        title: "Could not create assignment",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
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

        {loading ? <LoadingState label="Loading assignments…" /> : null}

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

        {!loading && !error && assignments && assignments.length === 0 ? (
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

        {!loading && !error && assignments && assignments.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Policy &amp; Scope</TableHead>
                <TableHead>Effective Range</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {assignments.map((a) => (
                <TableRow key={a.id}>
                  <TableCell>
                    <p className="font-medium text-foreground">
                      {POLICY_KIND_LABELS[a.policy_kind]} → {a.scope_type}
                      {a.scope_id ? ` (${a.scope_id})` : ""}
                    </p>
                    <p className="mt-0.5 text-xs text-foreground-muted">
                      Policy {a.policy_id}
                      {a.leave_type_id ? ` · Leave type ${a.leave_type_id}` : ""}
                      {a.reason ? ` · ${a.reason}` : ""}
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
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}

        {!loading && !error && pagination ? (
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
            <FormField id="assign-kind" label="Policy kind" required>
              <NativeSelect
                value={form.policyKind}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    policyKind: e.target.value as PolicyKind,
                    policyId: "",
                    leaveTypeId: "",
                  }))
                }
              >
                {POLICY_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {POLICY_KIND_LABELS[kind]}
                  </option>
                ))}
              </NativeSelect>
            </FormField>

            {isLeavePolicy ? (
              <FormField
                id="assign-leave-type"
                label="Leave type"
                required
                description="A company may assign a different leave policy per leave type at the same scope (LD-11)."
              >
                <NativeSelect
                  value={form.leaveTypeId}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, leaveTypeId: e.target.value, policyId: "" }))
                  }
                >
                  <option value="">Choose…</option>
                  {leaveTypeOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {optionLabel(option)}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
            ) : null}

            <FormField
              id="assign-policy"
              label="Policy"
              required
              description={
                isLeavePolicy && !form.leaveTypeId ? "Choose a leave type first." : undefined
              }
            >
              <NativeSelect
                value={form.policyId}
                disabled={isLeavePolicy && !form.leaveTypeId}
                onChange={(e) => setForm((f) => ({ ...f, policyId: e.target.value }))}
              >
                <option value="">Choose…</option>
                {visiblePolicyOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {optionLabel(option)}
                  </option>
                ))}
              </NativeSelect>
            </FormField>

            <FormField id="assign-scope-type" label="Scope" required>
              <NativeSelect
                value={form.scopeType}
                onChange={(e) =>
                  setForm((f) => ({ ...f, scopeType: e.target.value as ScopeType, scopeId: "" }))
                }
              >
                {SCOPE_TYPES.map((scope) => (
                  <option key={scope} value={scope}>
                    {scope}
                  </option>
                ))}
              </NativeSelect>
            </FormField>

            {form.scopeType !== "COMPANY" && SCOPE_LIST_PATH[form.scopeType] ? (
              <FormField id="assign-scope-id" label={`${form.scopeType} target`} required>
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
              <FormField
                id="assign-employee-id"
                label="Employee ID"
                required
                description="Paste the employee's ID (visible on their profile page URL)."
              >
                <Input
                  value={form.scopeId}
                  onChange={(e) => setForm((f) => ({ ...f, scopeId: e.target.value }))}
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

            <FormField id="assign-reason" label="Reason (optional)">
              <Input
                value={form.reason}
                onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
              />
            </FormField>

            {formError ? <p className="text-sm text-danger">{formError}</p> : null}
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
            <Button type="button" onClick={() => void handleCreate()} disabled={saving}>
              {saving ? "Creating…" : "Create assignment"}
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
