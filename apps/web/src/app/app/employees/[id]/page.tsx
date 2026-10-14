"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { EmployeeAttendancePanel } from "@/components/attendance/employee-attendance-panel";
import { ConcurrencyConflictBanner } from "@/components/employee/concurrency-conflict-banner";
import { AssignmentPanel } from "@/components/employee/assignment-panel";
import { BankingPanel } from "@/components/employee/banking-panel";
import { CompensationPanel } from "@/components/employee/compensation-panel";
import { DocumentPanel } from "@/components/employee/document-panel";
import { SalaryPanel } from "@/components/payroll/salary-panel";
import { EmployeeForm } from "@/components/employee/employee-form";
import { EmployeeOverview } from "@/components/employee/employee-overview";
import { EmployeeStatusBadge } from "@/components/employee/employee-status-badge";
import { EmploymentPanel } from "@/components/employee/employment-panel";
import { StatutoryPanel } from "@/components/employee/statutory-panel";
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
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { Employee } from "@/lib/employee/types";
import {
  buildUpdatePatch,
  employeeToFormValues,
  validateEmployeeForm,
  type EmployeeFormErrors,
  type EmployeeFormValues,
} from "@/lib/employee/validate-employee";
import { cn } from "@/lib/utils";

type TabKey =
  | "overview"
  | "employment"
  | "assignment"
  | "compensation"
  | "salary"
  | "statutory"
  | "banking"
  | "documents"
  | "attendance";

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "employment", label: "Employment" },
  { key: "assignment", label: "Assignment" },
  { key: "compensation", label: "Compensation" },
  { key: "salary", label: "Salary" },
  { key: "statutory", label: "Statutory" },
  { key: "banking", label: "Banking" },
  { key: "documents", label: "Documents" },
  { key: "attendance", label: "Attendance" },
];

function employeeName(employee: Employee): string {
  return employee.display_name?.trim() || [employee.first_name, employee.last_name].filter(Boolean).join(" ");
}

export default function EmployeeDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const { can } = usePermissions();

  const [employee, setEmployee] = useState<Employee | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [tab, setTab] = useState<TabKey>("overview");

  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<EmployeeFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<EmployeeFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [statusChanging, setStatusChanging] = useState(false);

  const [confirmProbationOpen, setConfirmProbationOpen] = useState(false);
  const [confirmingProbation, setConfirmingProbation] = useState(false);

  const [inviting, setInviting] = useState(false);

  const loadEmployee = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<Employee>(`/employees/${params.id}`);
      setEmployee(data);
      return data;
    } catch (err) {
      setEmployee(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
      return null;
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void loadEmployee();
  }, [loadEmployee]);

  function startEditing() {
    if (!employee) return;
    setFormValues(employeeToFormValues(employee));
    setFormErrors({});
    setStaleMessage(null);
    setEditing(true);
  }

  function cancelEditing() {
    setEditing(false);
    setFormValues(null);
    setFormErrors({});
    setStaleMessage(null);
  }

  async function handleSave() {
    if (!employee || !formValues) return;

    const clientErrors = validateEmployeeForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    const patch = buildUpdatePatch(formValues, employee);
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      setFormValues(null);
      toast({ title: "No changes to save", variant: "default" });
      return;
    }

    setSaving(true);
    setFormErrors({});
    setStaleMessage(null);
    try {
      const updated = await apiClient.patch<Employee>(`/employees/${employee.id}`, patch, {
        ifMatch: String(employee.version),
      });
      setEmployee(updated);
      setEditing(false);
      setFormValues(null);
      toast({ title: "Employee saved", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("This employee record was changed by someone else.");
          return;
        }
        if (err.status === 422) {
          setFormErrors({
            firstName: getFieldError(err.details, "first_name"),
            personalEmail: getFieldError(err.details, "personal_email"),
          });
          return;
        }
        if (err.status === 403) {
          toast({ title: "You don't have permission to edit this employee", variant: "danger" });
          setEditing(false);
          return;
        }
      }
      toast({ title: "Could not save employee", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatest() {
    const latest = await loadEmployee();
    if (latest) {
      setEditing(false);
      setFormValues(null);
      setStaleMessage(null);
      toast({ title: "Employee reloaded", variant: "success" });
    }
  }

  async function handleToggleStatus() {
    if (!employee) return;
    setStatusChanging(true);
    try {
      if (employee.is_active) {
        const updated = await apiClient.delete<Employee>(`/employees/${employee.id}`, {
          ifMatch: String(employee.version),
        });
        setEmployee(updated);
        toast({ title: "Employee deactivated", variant: "success" });
      } else {
        const updated = await apiClient.patch<Employee>(
          `/employees/${employee.id}`,
          { is_active: true },
          { ifMatch: String(employee.version) },
        );
        setEmployee(updated);
        toast({ title: "Employee reactivated", variant: "success" });
      }
      setConfirmOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === "STALE_RESOURCE") {
        toast({
          title: "Could not update employee status",
          description: "This employee record was changed by someone else. Reload and try again.",
          variant: "danger",
        });
        setConfirmOpen(false);
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        toast({ title: "You don't have permission to do that", variant: "danger" });
        setConfirmOpen(false);
        return;
      }
      toast({
        title: "Could not update employee status",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setStatusChanging(false);
    }
  }

  async function handleConfirmProbation() {
    if (!employee) return;
    setConfirmingProbation(true);
    try {
      const updated = await apiClient.post<Employee>(
        `/employees/${employee.id}/confirm`,
        {},
        { ifMatch: String(employee.version) },
      );
      setEmployee(updated);
      toast({ title: "Employee confirmed", variant: "success" });
      setConfirmProbationOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === "STALE_RESOURCE") {
        toast({
          title: "Could not confirm employee",
          description: "This employee record was changed by someone else. Reload and try again.",
          variant: "danger",
        });
        setConfirmProbationOpen(false);
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        toast({ title: "You don't have permission to do that", variant: "danger" });
        setConfirmProbationOpen(false);
        return;
      }
      toast({
        title: "Could not confirm employee",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setConfirmingProbation(false);
    }
  }

  async function handleInvite() {
    if (!employee) return;
    setInviting(true);
    try {
      const result = await apiClient.post<{ email: string; email_sent: boolean }>(
        `/employees/${employee.id}/invite`,
        {},
      );
      toast({
        title: `Invite sent to ${result.email}`,
        description: result.email_sent
          ? undefined
          : "The invite was created, but the email could not be delivered — share the link manually if needed.",
        variant: "success",
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast({ title: "This employee already has a login account", variant: "danger" });
        return;
      }
      if (err instanceof ApiError && err.status === 422) {
        toast({
          title: "Can't invite this employee",
          description: "Add a personal email to their profile first.",
          variant: "danger",
        });
        return;
      }
      toast({ title: "Could not send invite", description: describeApiError(err), variant: "danger" });
    } finally {
      setInviting(false);
    }
  }

  const canUpdate = can("EMPLOYEE.UPDATE");
  const canDeactivate = can("EMPLOYEE.DEACTIVATE");
  const canConfirm = can("EMPLOYEE.CONFIRM");
  const canInvite = can("EMPLOYEE.INVITE");

  return (
    <div className="space-y-6">
      <div>
        <Link href="/app/employees" className="text-sm text-foreground-secondary hover:underline">
          ← Employees
        </Link>
      </div>

      <PageHeader
        title={employee ? employeeName(employee) || employee.employee_code : "Employee"}
        description={employee ? `Employee code ${employee.employee_code}` : undefined}
        actions={
          employee && !editing ? (
            <div className="flex items-center gap-2">
              {canConfirm && employee.status === "PROBATION" ? (
                <Button type="button" variant="outline" onClick={() => setConfirmProbationOpen(true)}>
                  Confirm
                </Button>
              ) : null}
              {canInvite ? (
                <Button type="button" variant="outline" onClick={() => void handleInvite()} disabled={inviting}>
                  {inviting ? "Inviting…" : "Invite"}
                </Button>
              ) : null}
              {canDeactivate ? (
                <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)}>
                  {employee.is_active ? "Deactivate" : "Reactivate"}
                </Button>
              ) : null}
              {canUpdate ? (
                <Button type="button" onClick={startEditing}>
                  Edit
                </Button>
              ) : null}
            </div>
          ) : null
        }
      />

      {employee ? (
        <div className="flex flex-wrap items-center gap-2">
          <EmployeeStatusBadge status={employee.status} />
          <Badge variant={employee.is_active ? "secondary" : "outline"}>
            {employee.is_active ? "Active" : "Inactive"}
          </Badge>
        </div>
      ) : null}

      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label="Loading employee…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this employee."
                  : error.status === 404
                    ? "This employee could not be found, or you don't have access to it."
                    : error.message
              }
              onRetry={error.status === 404 ? undefined : () => void loadEmployee()}
            />
          </CardContent>
        </Card>
      ) : null}

      {staleMessage ? (
        <ConcurrencyConflictBanner message={staleMessage} onReload={() => void reloadLatest()} onCancel={cancelEditing} />
      ) : null}

      {!loading && !error && employee && editing && formValues ? (
        <Card>
          <CardContent className="space-y-6 pt-6">
            <EmployeeForm values={formValues} errors={formErrors} onChange={setFormValues} />
            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={() => void handleSave()} disabled={saving}>
                {saving ? "Saving…" : "Save changes"}
              </Button>
              <Button type="button" variant="outline" onClick={cancelEditing} disabled={saving}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && employee && !editing ? (
        <div className="space-y-4">
          <div className="flex gap-1 overflow-x-auto border-b border-border" role="tablist">
            {TABS.map((item) => (
              <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={tab === item.key}
                onClick={() => setTab(item.key)}
                className={cn(
                  "shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                  tab === item.key
                    ? "border-primary text-foreground"
                    : "border-transparent text-foreground-muted hover:text-foreground",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>

          {tab === "overview" ? <EmployeeOverview employee={employee} /> : null}
          {tab === "employment" ? <EmploymentPanel employeeId={employee.id} /> : null}
          {tab === "assignment" ? <AssignmentPanel employeeId={employee.id} /> : null}
          {tab === "compensation" ? <CompensationPanel employeeId={employee.id} /> : null}
          {tab === "salary" ? <SalaryPanel employeeId={employee.id} /> : null}
          {tab === "statutory" ? <StatutoryPanel employeeId={employee.id} /> : null}
          {tab === "banking" ? <BankingPanel employeeId={employee.id} /> : null}
          {tab === "documents" ? <DocumentPanel employeeId={employee.id} /> : null}
          {tab === "attendance" ? (
            <EmployeeAttendancePanel employeeId={employee.id} employeeLabel={employeeName(employee)} />
          ) : null}
        </div>
      ) : null}

      <Dialog open={confirmOpen} onOpenChange={(open) => (!statusChanging ? setConfirmOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{employee?.is_active ? "Deactivate employee?" : "Reactivate employee?"}</DialogTitle>
            <DialogDescription>
              {employee?.is_active
                ? "This employee will no longer be active in the system. You can reactivate them later."
                : "This employee will become active again."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setConfirmOpen(false)} disabled={statusChanging}>
              Cancel
            </Button>
            <Button
              type="button"
              variant={employee?.is_active ? "destructive" : "default"}
              onClick={() => void handleToggleStatus()}
              disabled={statusChanging}
            >
              {statusChanging ? "Saving…" : employee?.is_active ? "Deactivate" : "Reactivate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={confirmProbationOpen}
        onOpenChange={(open) => (!confirmingProbation ? setConfirmProbationOpen(open) : null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm employee?</DialogTitle>
            <DialogDescription>
              This moves the employee from Probation to Active. This action cannot be reversed.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirmProbationOpen(false)}
              disabled={confirmingProbation}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handleConfirmProbation()}
              disabled={confirmingProbation}
            >
              {confirmingProbation ? "Confirming…" : "Confirm"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
