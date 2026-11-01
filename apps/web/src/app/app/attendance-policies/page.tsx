"use client";

import { ClipboardList, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { FaceEnrollmentPolicyCard } from "@/components/attendance/face-enrollment-policy-card";
import { AttendancePolicyForm } from "@/components/attendance-policy/attendance-policy-form";
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
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { usePermissions } from "@/lib/auth/use-permissions";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { AttendancePolicy } from "@/lib/attendance-policy/types";
import {
  EMPTY_ATTENDANCE_POLICY_FORM_VALUES,
  buildAttendancePolicyCreatePayload,
  validateAttendancePolicyForm,
  type AttendancePolicyFormErrors,
  type AttendancePolicyFormValues,
} from "@/lib/attendance-policy/validate-attendance-policy";

export default function AttendancePoliciesPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const [policies, setPolicies] = useState<AttendancePolicy[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<AttendancePolicyFormValues>(
    EMPTY_ATTENDANCE_POLICY_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<AttendancePolicyFormErrors>({});
  const [saving, setSaving] = useState(false);

  const loadPolicies = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<AttendancePolicy[]>("/attendance-policies");
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
    setFormValues(EMPTY_ATTENDANCE_POLICY_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateAttendancePolicyForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }
    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<AttendancePolicy>(
        "/attendance-policies",
        buildAttendancePolicyCreatePayload(formValues),
      );
      setCreateOpen(false);
      toast({
        title: "Attendance policy added — configure it on the Versions tab",
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
        toast({ title: "You don't have permission to add attendance policies", variant: "danger" });
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
        title="Attendance Policies"
        description="Grace, rounding, missing-punch, hour bands, and other rules for evaluating attendance against a schedule."
        actions={
          policies && policies.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add Policy
            </Button>
          ) : null
        }
      />

      {can("ATTENDANCE.FACE_ENROLLMENT_MANAGE") ? <FaceEnrollmentPolicyCard /> : null}

      <TableContainer>
        {loading ? <LoadingState label="Loading attendance policies…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view attendance policies."
                  : error.message
              }
              onRetry={() => void loadPolicies()}
            />
          </div>
        ) : null}

        {!loading && !error && policies && policies.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={ClipboardList}
              title="No attendance policies have been configured yet."
              description="Add a policy, then define its grace/rounding/hour-band rules on its Versions tab."
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
                      href={`/app/attendance-policies/${policy.id}`}
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
                    <Link
                      href={`/app/attendance-policies/${policy.id}`}
                      className="text-xs font-medium text-primary hover:underline"
                    >
                      Configure
                    </Link>
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
            <DialogTitle>Add Attendance Policy</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <AttendancePolicyForm
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
