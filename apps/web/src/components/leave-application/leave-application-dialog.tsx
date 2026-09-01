"use client";

import { useEffect, useState } from "react";

import { FormField } from "@/components/common/form-field";
import { useToast } from "@/components/common/toast";
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
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { LEAVE_HALF_DAY_VALUES, type LeaveApplication } from "@/lib/leave-application/types";
import {
  buildLeaveApplicationCreatePayload,
  emptyLeaveApplicationFormValues,
  validateLeaveApplicationForm,
  type LeaveApplicationFormErrors,
  type LeaveApplicationFormValues,
} from "@/lib/leave-application/validate-leave-application";
import type { LeaveType } from "@/lib/leave-type/types";

interface EmployeeOption {
  id: string;
  first_name: string;
  last_name: string | null;
  employee_code: string | null;
}

function employeeLabelFor(employee: EmployeeOption): string {
  const name = [employee.first_name, employee.last_name].filter(Boolean).join(" ");
  return employee.employee_code ? `${name} (${employee.employee_code})` : name;
}

const HALF_DAY_LABELS: Record<string, string> = {
  FIRST_HALF: "First half",
  SECOND_HALF: "Second half",
};

interface LeaveApplicationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `"SELF"` never shows an employee field — the backend defaults to the caller's own linked
   * employee record. `"ON_BEHALF"` always needs a target employee: pre-filled and locked when
   * `employeeId` is given, otherwise an editable picker. */
  mode: "SELF" | "ON_BEHALF";
  employeeId?: string;
  employeeLabel?: string;
  onCreated: (application: LeaveApplication) => void;
}

/** `POST /v1/leave-applications` (LEAVE_DECISION_LOG.md LD-02/LD-06). The backend is the source
 * of truth for which policy rules apply (reason/attachment required, half-day allowed, backdating
 * window, monthly cap, balance sufficiency) — this dialog surfaces those as field-level 422s
 * rather than guessing them client-side. */
export function LeaveApplicationDialog({
  open,
  onOpenChange,
  mode,
  employeeId,
  employeeLabel,
  onCreated,
}: LeaveApplicationDialogProps) {
  const { toast } = useToast();

  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([]);
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [selectedEmployeeId, setSelectedEmployeeId] = useState(employeeId ?? "");
  const [values, setValues] = useState<LeaveApplicationFormValues>(() =>
    emptyLeaveApplicationFormValues(),
  );
  const [errors, setErrors] = useState<LeaveApplicationFormErrors & { employeeId?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const needsEmployeePicker = mode === "ON_BEHALF" && !employeeId;

  useEffect(() => {
    if (!open) return;
    setValues(emptyLeaveApplicationFormValues());
    setSelectedEmployeeId(employeeId ?? "");
    setErrors({});
    setFormError(null);
    void apiClient
      .get<LeaveType[]>("/leave-types")
      .then(setLeaveTypes)
      .catch(() => setLeaveTypes([]));
    if (mode === "ON_BEHALF" && !employeeId) {
      void apiClient
        .get<EmployeeOption[]>("/employees")
        .then(setEmployees)
        .catch(() => setEmployees([]));
    }
  }, [open, mode, employeeId]);

  async function handleSubmit() {
    const clientErrors: LeaveApplicationFormErrors & { employeeId?: string } =
      validateLeaveApplicationForm(values);
    if (needsEmployeePicker && !selectedEmployeeId) {
      clientErrors.employeeId = "Choose an employee.";
    }
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }
    setSaving(true);
    setErrors({});
    setFormError(null);
    try {
      const targetEmployeeId = mode === "ON_BEHALF" ? employeeId || selectedEmployeeId : undefined;
      const created = await apiClient.post<LeaveApplication>(
        "/leave-applications",
        buildLeaveApplicationCreatePayload(values, targetEmployeeId),
      );
      onCreated(created);
      onOpenChange(false);
      toast({
        title:
          created.status === "APPROVED" ? "Leave application submitted and approved" : "Leave application submitted",
        variant: "success",
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setErrors({
          leaveTypeId: getFieldError(err.details, "leave_type_id"),
          startDate: getFieldError(err.details, "start_date"),
          endDate: getFieldError(err.details, "end_date"),
          reason: getFieldError(err.details, "reason"),
          attachment: getFieldError(err.details, "attachment_reference"),
        });
        setFormError(describeApiError(err));
        return;
      }
      if (err instanceof ApiError && (err.status === 409 || err.status === 403)) {
        setFormError(describeApiError(err));
        return;
      }
      setFormError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (!saving ? onOpenChange(next) : null)}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Apply for leave</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          {mode === "ON_BEHALF" && employeeId ? (
            <FormField id="leave-application-employee-locked" label="Employee">
              <Input value={employeeLabel ?? employeeId} disabled />
            </FormField>
          ) : null}
          {needsEmployeePicker ? (
            <FormField
              id="leave-application-employee"
              label="Employee"
              required
              error={errors.employeeId}
            >
              <NativeSelect
                value={selectedEmployeeId}
                onChange={(e) => setSelectedEmployeeId(e.target.value)}
              >
                <option value="">Choose…</option>
                {employees.map((emp) => (
                  <option key={emp.id} value={emp.id}>
                    {employeeLabelFor(emp)}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          ) : null}

          <FormField id="leave-application-type" label="Leave type" required error={errors.leaveTypeId}>
            <NativeSelect
              value={values.leaveTypeId}
              onChange={(e) => setValues((c) => ({ ...c, leaveTypeId: e.target.value }))}
            >
              <option value="">Choose…</option>
              {leaveTypes.map((leaveType) => (
                <option key={leaveType.id} value={leaveType.id}>
                  {leaveType.name} ({leaveType.code})
                </option>
              ))}
            </NativeSelect>
          </FormField>

          <div className="grid grid-cols-2 gap-4">
            <FormField id="leave-application-start" label="Start date" required error={errors.startDate}>
              <Input
                type="date"
                value={values.startDate}
                onChange={(e) =>
                  setValues((c) => ({
                    ...c,
                    startDate: e.target.value,
                    halfDay: c.endDate === e.target.value || !c.endDate ? c.halfDay : "",
                  }))
                }
              />
            </FormField>
            <FormField id="leave-application-end" label="End date" required error={errors.endDate}>
              <Input
                type="date"
                value={values.endDate}
                onChange={(e) => setValues((c) => ({ ...c, endDate: e.target.value }))}
              />
            </FormField>
          </div>

          {values.startDate && values.startDate === values.endDate ? (
            <FormField id="leave-application-half-day" label="Half day" description="Optional — leave full for a whole day.">
              <NativeSelect
                value={values.halfDay}
                onChange={(e) =>
                  setValues((c) => ({
                    ...c,
                    halfDay: e.target.value as LeaveApplicationFormValues["halfDay"],
                  }))
                }
              >
                <option value="">Full day</option>
                {LEAVE_HALF_DAY_VALUES.map((half) => (
                  <option key={half} value={half}>
                    {HALF_DAY_LABELS[half]}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          ) : null}

          <FormField
            id="leave-application-reason"
            label="Reason"
            error={errors.reason}
            description="Required by most policies."
          >
            <Input
              value={values.reason}
              onChange={(e) => setValues((c) => ({ ...c, reason: e.target.value }))}
              maxLength={2000}
            />
          </FormField>

          <FormField
            id="leave-application-attachment"
            label="Attachment reference"
            error={errors.attachment}
            description="Optional — a link or reference id for supporting evidence."
          >
            <Input
              value={values.attachmentReference}
              onChange={(e) => setValues((c) => ({ ...c, attachmentReference: e.target.value }))}
              maxLength={500}
            />
          </FormField>

          {formError ? (
            <p role="alert" className="text-sm text-danger">
              {formError}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void handleSubmit()} disabled={saving}>
            {saving ? "Submitting…" : "Submit application"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
