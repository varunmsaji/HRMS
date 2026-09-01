"use client";

import { ClipboardList } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { LeavePolicyForm } from "@/components/leave-policy/leave-policy-form";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
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
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { LeavePolicy } from "@/lib/leave-policy/types";
import {
  EMPTY_LEAVE_POLICY_FORM_VALUES,
  buildLeavePolicyCreatePayload,
  validateLeavePolicyForm,
  type LeavePolicyFormErrors,
  type LeavePolicyFormValues,
} from "@/lib/leave-policy/validate-leave-policy";
import type { LeaveType } from "@/lib/leave-type/types";

export default function LeavePoliciesPage() {
  const { toast } = useToast();

  const [policies, setPolicies] = useState<LeavePolicy[] | null>(null);
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<LeavePolicyFormValues>(
    EMPTY_LEAVE_POLICY_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<LeavePolicyFormErrors>({});
  const [saving, setSaving] = useState(false);

  const leaveTypeById = useMemo(() => {
    const map = new Map<string, LeaveType>();
    for (const lt of leaveTypes) map.set(lt.id, lt);
    return map;
  }, [leaveTypes]);

  const loadPolicies = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<LeavePolicy[]>("/leave-policies");
      setPolicies(data);
    } catch (err) {
      setPolicies(null);
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
    void loadPolicies();
    void apiClient
      .get<LeaveType[]>("/leave-types")
      .then(setLeaveTypes)
      .catch(() => setLeaveTypes([]));
  }, [loadPolicies]);

  function openCreate() {
    setFormValues(EMPTY_LEAVE_POLICY_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateLeavePolicyForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }
    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<LeavePolicy>(
        "/leave-policies",
        buildLeavePolicyCreatePayload(formValues),
      );
      setCreateOpen(false);
      toast({ title: "Leave policy added — configure it on the Versions tab", variant: "success" });
      await loadPolicies();
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setFormErrors({ leaveTypeId: "This leave type could not be found." });
        return;
      }
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({ name: getFieldError(err.details, "name") });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to add leave policies", variant: "danger" });
        return;
      }
      toast({ title: "Could not add policy", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Leave Policies"
        description="Request/approval rules, accrual, and the sandwich rule for each leave type."
        actions={
          policies && policies.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              Add Policy
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading leave policies…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view leave policies."
                  : error.message
              }
              onRetry={() => void loadPolicies()}
            />
          ) : null}

          {!loading && !error && policies && policies.length === 0 ? (
            <EmptyState
              icon={ClipboardList}
              title="No leave policies have been configured yet."
              description="Add a policy for a leave type, then define its rules on its Versions tab."
              action={
                <Button type="button" onClick={openCreate}>
                  Add Policy
                </Button>
              }
            />
          ) : null}

          {!loading && !error && policies && policies.length > 0 ? (
            <ul className="divide-y divide-border">
              {policies.map((policy) => (
                <li key={policy.id} className="py-4 first:pt-0 last:pb-0">
                  <Link
                    href={`/app/leave-policies/${policy.id}`}
                    className="flex items-center justify-between gap-4 rounded-md px-2 py-1 -mx-2 hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <div>
                      <p className="text-sm font-medium text-foreground">
                        {policy.name}
                        {policy.code ? (
                          <span className="text-foreground-muted"> ({policy.code})</span>
                        ) : null}
                      </p>
                      <p className="mt-0.5 text-xs text-foreground-muted">
                        {leaveTypeById.get(policy.leave_type_id)?.name ?? policy.leave_type_id}
                      </p>
                    </div>
                    <Badge variant={policy.is_active ? "secondary" : "outline"}>
                      {policy.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Leave Policy</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <LeavePolicyForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
              idPrefix="create-"
              leaveTypeOptions={leaveTypes}
            />
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
              {saving ? "Adding…" : "Add policy"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
