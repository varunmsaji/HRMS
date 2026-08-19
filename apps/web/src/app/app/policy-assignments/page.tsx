"use client";

import { Link2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
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
  scopeType: ScopeType;
  scopeId: string;
  effectiveFrom: string;
  reason: string;
}

const EMPTY_FORM: CreateFormState = {
  policyKind: "ATTENDANCE_POLICY",
  policyId: "",
  scopeType: "COMPANY",
  scopeId: "",
  effectiveFrom: "",
  reason: "",
};

export default function PolicyAssignmentsPage() {
  const { toast } = useToast();
  const [filterKind, setFilterKind] = useState<PolicyKind | "">("");
  const [assignments, setAssignments] = useState<PolicyAssignment[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<CreateFormState>(EMPTY_FORM);
  const [policyOptions, setPolicyOptions] = useState<NamedOption[]>([]);
  const [scopeOptions, setScopeOptions] = useState<NamedOption[]>([]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const loadAssignments = useCallback(async (kind: PolicyKind | "") => {
    setLoading(true);
    setError(null);
    try {
      const query = kind ? `?policy_kind=${kind}` : "";
      const data = await apiClient.get<PolicyAssignment[]>(`/policy-assignments${query}`);
      setAssignments(data);
    } catch (err) {
      setAssignments(null);
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
    void loadAssignments(filterKind);
  }, [filterKind, loadAssignments]);

  useEffect(() => {
    if (!createOpen) return;
    void apiClient
      .get<NamedOption[]>(POLICY_KIND_LIST_PATH[form.policyKind])
      .then(setPolicyOptions)
      .catch(() => setPolicyOptions([]));
  }, [createOpen, form.policyKind]);

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
    setSaving(true);
    setFormError(null);
    try {
      await apiClient.post<PolicyAssignment>("/policy-assignments", {
        policy_kind: form.policyKind,
        policy_id: form.policyId,
        scope_type: form.scopeType,
        scope_id: form.scopeType === "COMPANY" ? null : form.scopeId,
        effective_from: form.effectiveFrom,
        reason: form.reason.trim() || null,
      });
      setCreateOpen(false);
      toast({ title: "Assignment created", variant: "success" });
      await loadAssignments(filterKind);
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
        title="Policy Assignments"
        description="Assign a Work Calendar, Weekly-Off Pattern, Attendance/Overtime/Regularization Policy to a scope. Most specific wins: EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT > BRANCH > LEGAL_ENTITY > COMPANY."
        actions={
          <Button type="button" onClick={openCreate}>
            New Assignment
          </Button>
        }
      />

      <Card>
        <CardContent className="space-y-4 pt-6">
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

          {loading ? <LoadingState label="Loading assignments…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view policy assignments."
                  : error.message
              }
              onRetry={() => void loadAssignments(filterKind)}
            />
          ) : null}

          {!loading && !error && assignments && assignments.length === 0 ? (
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
          ) : null}

          {!loading && !error && assignments && assignments.length > 0 ? (
            <ul className="divide-y divide-border">
              {assignments.map((a) => (
                <li key={a.id} className="py-4 first:pt-0 last:pb-0">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <p className="text-sm font-medium text-foreground">
                        {POLICY_KIND_LABELS[a.policy_kind]} → {a.scope_type}
                        {a.scope_id ? ` (${a.scope_id})` : ""}
                      </p>
                      <p className="mt-0.5 text-xs text-foreground-muted">
                        Policy {a.policy_id} · {a.effective_from} – {a.effective_to ?? "open"}
                        {a.reason ? ` · ${a.reason}` : ""}
                      </p>
                    </div>
                    <Badge variant={a.effective_to === null ? "secondary" : "outline"}>
                      {a.effective_to === null ? "Current" : `Ended ${a.effective_to}`}
                    </Badge>
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

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

            <FormField id="assign-policy" label="Policy" required>
              <NativeSelect
                value={form.policyId}
                onChange={(e) => setForm((f) => ({ ...f, policyId: e.target.value }))}
              >
                <option value="">Choose…</option>
                {policyOptions.map((option) => (
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
    </div>
  );
}
