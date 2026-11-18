"use client";

import { ArrowLeft, MoreHorizontal, Pencil, Power, Send, UserCheck } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { EmployeeAttendancePanel } from "@/components/attendance/employee-attendance-panel";
import { ConcurrencyConflictBanner } from "@/components/employee/concurrency-conflict-banner";
import { AssignmentChangeDialog } from "@/components/employee/assignment-change-dialog";
import { AssignmentPanel } from "@/components/employee/assignment-panel";
import { BankingPanel } from "@/components/employee/banking-panel";
import { CompensationPanel } from "@/components/employee/compensation-panel";
import { DocumentPanel } from "@/components/employee/document-panel";
import { SalaryPanel } from "@/components/payroll/salary-panel";
import { EmployeeForm } from "@/components/employee/employee-form";
import { EmployeeOverview } from "@/components/employee/employee-overview";
import { EmployeeProfileHero } from "@/components/employee/employee-profile-hero";
import {
  EmployeeSectionNav,
  isEmployeeSection,
  type EmployeeSectionKey,
} from "@/components/employee/employee-section-nav";
import { EmploymentPanel } from "@/components/employee/employment-panel";
import { IdentityPanel } from "@/components/employee/identity-panel";
import { RecordListPanel } from "@/components/employee/record-list-panel";
import { StatutoryPanel } from "@/components/employee/statutory-panel";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import { employeeFullName } from "@/lib/employee/names";
import type { AssignmentChangeType, Employee } from "@/lib/employee/types";
import {
  buildUpdatePatch,
  employeeToFormValues,
  validateEmployeeForm,
  type EmployeeFormErrors,
  type EmployeeFormValues,
} from "@/lib/employee/validate-employee";
import { DEPENDENTS_SECTION, EDUCATION_SECTION, EXPERIENCE_SECTION } from "@/lib/employee/record-sections";
import { useEmployeeWorkSummary } from "@/lib/employee/use-employee-work-summary";

function employeeName(employee: Employee): string {
  return employeeFullName(employee);
}

export default function EmployeeDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const { can } = usePermissions();

  const [employee, setEmployee] = useState<Employee | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [tab, setTabState] = useState<EmployeeSectionKey>("overview");
  const work = useEmployeeWorkSummary(employee?.id ?? null);

  // The open section lives in ?tab= so a reload or a shared link lands on the same section.
  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("tab");
    if (isEmployeeSection(fromUrl)) setTabState(fromUrl);
  }, []);

  function setTab(next: EmployeeSectionKey) {
    // Employment and Assignment edit what the header and Overview show; refresh on the way out.
    if (next !== tab && (tab === "employment" || tab === "assignment")) work.reload();
    setTabState(next);
    const url = new URL(window.location.href);
    if (next === "overview") url.searchParams.delete("tab");
    else url.searchParams.set("tab", next);
    window.history.replaceState(window.history.state, "", url);
  }

  const [editing, setEditing] = useState(false);
  // The assignment-change dialog, opened from the Overview's edit buttons.
  const [workDialog, setWorkDialog] = useState<{ open: boolean; changeType: AssignmentChangeType | "" }>({
    open: false,
    changeType: "",
  });
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
      toast({
        title: "Could not save employee",
        description: describeApiError(err),
        variant: "danger",
      });
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
      toast({
        title: "Could not send invite",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setInviting(false);
    }
  }

  const canUpdate = can("EMPLOYEE.UPDATE");
  const canDeactivate = can("EMPLOYEE.DEACTIVATE");
  const canConfirm = can("EMPLOYEE.CONFIRM");
  const canInvite = can("EMPLOYEE.INVITE");
  const canChangeWork = can("EMPLOYEE.TRANSFER") || can("EMPLOYEE.PROMOTE");

  return (
    <div className="space-y-6">
      <Link
        href="/app/employees"
        className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground-secondary transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
        <span>Employees</span>
      </Link>

      {employee ? (
        <EmployeeProfileHero
          employee={employee}
          work={work.data}
          workLoading={work.loading}
          actions={
            !editing ? (
              <>
                {canConfirm && employee.status === "PROBATION" ? (
                  <Button type="button" variant="outline" onClick={() => setConfirmProbationOpen(true)}>
                    <UserCheck className="h-4 w-4" aria-hidden="true" />
                    Confirm
                  </Button>
                ) : null}
                {canUpdate ? (
                  <Button type="button" onClick={startEditing}>
                    <Pencil className="h-4 w-4" aria-hidden="true" />
                    Edit
                  </Button>
                ) : null}
                {canInvite || canDeactivate ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button type="button" variant="outline" size="icon" aria-label="More actions">
                        <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="min-w-[12rem]">
                      {canInvite ? (
                        <DropdownMenuItem disabled={inviting} onSelect={() => void handleInvite()}>
                          <Send className="h-4 w-4" aria-hidden="true" />
                          {inviting ? "Inviting…" : "Invite to log in"}
                        </DropdownMenuItem>
                      ) : null}
                      {canDeactivate ? (
                        <DropdownMenuItem
                          onSelect={() => setConfirmOpen(true)}
                          className={employee.is_active ? "text-danger focus:text-danger" : undefined}
                        >
                          <Power className="h-4 w-4" aria-hidden="true" />
                          {employee.is_active ? "Deactivate" : "Reactivate"}
                        </DropdownMenuItem>
                      ) : null}
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : null}
              </>
            ) : null
          }
        />
      ) : null}

      {loading ? (
        <Card>
          <CardContent>
            <LoadingState label="Loading employee…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent>
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
        <ConcurrencyConflictBanner
          message={staleMessage}
          onReload={() => void reloadLatest()}
          onCancel={cancelEditing}
        />
      ) : null}

      {!loading && !error && employee && editing && formValues ? (
        <Card>
          <CardContent className="space-y-6">
            <EmployeeForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
            />
            <div className="flex flex-wrap gap-2 border-t border-border pt-4">
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
        <div className="grid gap-5 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-6">
          <EmployeeSectionNav value={tab} onChange={setTab} />
          <div className="min-w-0 space-y-5">
          {tab === "overview" ? (
            <EmployeeOverview
              employee={employee}
              work={work.data}
              workLoading={work.loading}
              workError={work.error}
              actions={{
                canEditDetails: canUpdate,
                canChangeWork,
                onEditDetails: startEditing,
                onChangeWork: (changeType) => setWorkDialog({ open: true, changeType }),
                onOpenSection: setTab,
              }}
            />
          ) : null}
          {tab === "employment" ? <EmploymentPanel employeeId={employee.id} /> : null}
          {tab === "assignment" ? <AssignmentPanel employeeId={employee.id} /> : null}
          {tab === "compensation" ? <CompensationPanel employeeId={employee.id} /> : null}
          {tab === "salary" ? <SalaryPanel employeeId={employee.id} /> : null}
          {tab === "statutory" ? <StatutoryPanel employeeId={employee.id} /> : null}
          {tab === "banking" ? <BankingPanel employeeId={employee.id} /> : null}
          {tab === "identity" ? <IdentityPanel employeeId={employee.id} /> : null}
          {tab === "experience" ? <RecordListPanel employeeId={employee.id} section={EXPERIENCE_SECTION} /> : null}
          {tab === "education" ? <RecordListPanel employeeId={employee.id} section={EDUCATION_SECTION} /> : null}
          {tab === "dependents" ? <RecordListPanel employeeId={employee.id} section={DEPENDENTS_SECTION} /> : null}
          {tab === "documents" ? <DocumentPanel employeeId={employee.id} /> : null}
          {tab === "attendance" ? (
            <EmployeeAttendancePanel
              employeeId={employee.id}
              employeeLabel={employeeName(employee)}
            />
          ) : null}
          </div>
        </div>
      ) : null}

      {employee ? (
        <AssignmentChangeDialog
          employeeId={employee.id}
          open={workDialog.open}
          initialChangeType={workDialog.changeType}
          onOpenChange={(open) => setWorkDialog((prev) => ({ ...prev, open }))}
          onSaved={() => work.reload()}
        />
      ) : null}

      <Dialog
        open={confirmOpen}
        onOpenChange={(open) => (!statusChanging ? setConfirmOpen(open) : null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {employee?.is_active ? "Deactivate employee?" : "Reactivate employee?"}
            </DialogTitle>
            <DialogDescription>
              {employee?.is_active
                ? "This employee will no longer be active in the system. You can reactivate them later."
                : "This employee will become active again."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={statusChanging}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant={employee?.is_active ? "destructive" : "default"}
              onClick={() => void handleToggleStatus()}
              disabled={statusChanging}
            >
              {statusChanging
                ? "Saving…"
                : employee?.is_active
                  ? "Deactivate"
                  : "Reactivate"}
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
