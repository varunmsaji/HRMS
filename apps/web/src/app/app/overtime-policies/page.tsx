"use client";

import { Plus, Timer } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { OvertimePolicyForm } from "@/components/overtime-policy/overtime-policy-form";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
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
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableRowAction,
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { OvertimePolicy } from "@/lib/overtime-policy/types";
import {
  EMPTY_OVERTIME_POLICY_FORM_VALUES,
  buildOvertimePolicyCreatePayload,
  validateOvertimePolicyForm,
  type OvertimePolicyFormErrors,
  type OvertimePolicyFormValues,
} from "@/lib/overtime-policy/validate-overtime-policy";

export default function OvertimePoliciesPage() {
  const { toast } = useToast();
  const [policies, setPolicies] = useState<OvertimePolicy[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<OvertimePolicyFormValues>(
    EMPTY_OVERTIME_POLICY_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<OvertimePolicyFormErrors>({});
  const [saving, setSaving] = useState(false);

  const loadPolicies = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<OvertimePolicy[]>("/overtime-policies");
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
  }, [loadPolicies]);

  function openCreate() {
    setFormValues(EMPTY_OVERTIME_POLICY_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateOvertimePolicyForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }
    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<OvertimePolicy>(
        "/overtime-policies",
        buildOvertimePolicyCreatePayload(formValues),
      );
      setCreateOpen(false);
      toast({
        title: "Overtime policy added — configure it on the Versions tab",
        variant: "success",
      });
      await loadPolicies();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({ name: getFieldError(err.details, "name") });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to add overtime policies", variant: "danger" });
        return;
      }
      toast({
        title: "Could not add policy",
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
        title="Overtime Policies"
        description="Eligibility, caps, approval chain, and rate rows for detecting overtime — Attendance may detect extra minutes, this policy decides what happens to them."
        actions={
          policies && policies.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add Policy
            </Button>
          ) : null
        }
      />

      <TableContainer>
        {loading ? <LoadingState label="Loading overtime policies…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view overtime policies."
                  : error.message
              }
              onRetry={() => void loadPolicies()}
            />
          </div>
        ) : null}

        {!loading && !error && policies && policies.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={Timer}
              title="No overtime policies have been configured yet."
              description="Add a policy, then define its eligibility/caps/approval rules on its Versions tab."
              action={
                <Button type="button" onClick={openCreate}>
                  Add Policy
                </Button>
              }
            />
          </div>
        ) : null}

        {!loading && !error && policies && policies.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Policy</TableHead>
                <TableHead>Code</TableHead>
                <TableHead>Status</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {policies.map((policy) => (
                <TableRow key={policy.id}>
                  <TableCell>
                    <Link
                      href={`/app/overtime-policies/${policy.id}`}
                      className="font-medium text-foreground hover:text-primary hover:underline"
                    >
                      {policy.name}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-foreground-secondary">
                    {policy.code ?? "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={policy.is_active ? "secondary" : "outline"}>
                      {policy.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell align="right">
                    <TableRowAction href={`/app/overtime-policies/${policy.id}`}>Configure</TableRowAction>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </TableContainer>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Overtime Policy</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <OvertimePolicyForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
              idPrefix="create-"
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
