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
import {
  REGULARIZATION_TYPES,
  REGULARIZATION_TYPE_LABELS,
  type RegularizationRequest,
} from "@/lib/regularization/types";
import {
  buildRegularizationCreatePayload,
  emptyRegularizationFormValues,
  validateRegularizationForm,
  type RegularizationCorrectionKind,
  type RegularizationFormErrors,
  type RegularizationFormValues,
} from "@/lib/regularization/validate-regularization";

interface ShiftOption {
  id: string;
  name: string;
  code: string | null;
}

interface EmployeeOption {
  id: string;
  first_name: string;
  last_name: string | null;
  employee_code: string | null;
}

function shiftLabel(shift: ShiftOption): string {
  return shift.code ? `${shift.name} (${shift.code})` : shift.name;
}

function employeeLabelFor(employee: EmployeeOption): string {
  const name = [employee.first_name, employee.last_name].filter(Boolean).join(" ");
  return employee.employee_code ? `${name} (${employee.employee_code})` : name;
}

interface RegularizationRequestDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `"SELF"` never shows an employee field — the backend defaults to the caller's own linked
   * employee record. `"ON_BEHALF"` always needs a target employee: pre-filled and locked when
   * `employeeId` is given (e.g. opened from an attendance day already scoped to one employee),
   * otherwise an editable picker (e.g. opened from the unfiltered "Team requests" list). */
  mode: "SELF" | "ON_BEHALF";
  employeeId?: string;
  employeeLabel?: string;
  /** Pre-fills the date when opened from an attendance day's detail page. */
  attendanceDate?: string;
  onCreated: (request: RegularizationRequest) => void;
}

/** `POST /v1/regularizations` (architecture §13/§25, WD-28). Every request needs either a
 * corrected shift (`WRONG_SHIFT`) or at least one corrected punch time — the backend is the
 * source of truth for which `request_type`s a policy allows and whether reason/attachment are
 * mandatory; this dialog surfaces those as field-level 422s rather than guessing them
 * client-side (see `validate-regularization.ts`). */
export function RegularizationRequestDialog({
  open,
  onOpenChange,
  mode,
  employeeId,
  employeeLabel,
  attendanceDate,
  onCreated,
}: RegularizationRequestDialogProps) {
  const { toast } = useToast();

  const [shifts, setShifts] = useState<ShiftOption[]>([]);
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [selectedEmployeeId, setSelectedEmployeeId] = useState(employeeId ?? "");
  const [values, setValues] = useState<RegularizationFormValues>(() =>
    emptyRegularizationFormValues(),
  );
  const [errors, setErrors] = useState<RegularizationFormErrors & { employeeId?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const needsEmployeePicker = mode === "ON_BEHALF" && !employeeId;

  useEffect(() => {
    if (!open) return;
    setValues(emptyRegularizationFormValues({ attendanceDate: attendanceDate ?? "" }));
    setSelectedEmployeeId(employeeId ?? "");
    setErrors({});
    setFormError(null);
    void apiClient
      .get<ShiftOption[]>("/shifts")
      .then(setShifts)
      .catch(() => setShifts([]));
    if (mode === "ON_BEHALF" && !employeeId) {
      void apiClient
        .getList<EmployeeOption>("/employees", { per_page: 100 })
        .then(({ data }) => setEmployees(data))
        .catch(() => setEmployees([]));
    }
  }, [open, attendanceDate, mode, employeeId]);

  function updateCorrectionKind(correctionKind: RegularizationCorrectionKind) {
    setValues((current) => ({ ...current, correctionKind }));
  }

  async function handleSubmit() {
    const clientErrors: RegularizationFormErrors & { employeeId?: string } =
      validateRegularizationForm(values);
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
      const created = await apiClient.post<RegularizationRequest>(
        "/regularizations",
        buildRegularizationCreatePayload(values, targetEmployeeId),
      );
      onCreated(created);
      onOpenChange(false);
      toast({ title: "Regularization request submitted", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setErrors({
          requestType: getFieldError(err.details, "request_type"),
          shiftId: getFieldError(err.details, "requested_shift_id"),
          reason: getFieldError(err.details, "reason"),
          attachment: getFieldError(err.details, "attachment_reference"),
          attendanceDate: getFieldError(err.details, "attendance_date"),
        });
        setFormError(describeApiError(err));
        return;
      }
      if (err instanceof ApiError && err.status === 409) {
        setFormError(describeApiError(err));
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setFormError("You don't have permission to submit this request.");
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
          <DialogTitle>Raise a regularization request</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          {mode === "ON_BEHALF" && employeeId ? (
            <FormField id="regularization-employee-locked" label="Employee">
              <Input value={employeeLabel ?? employeeId} disabled />
            </FormField>
          ) : null}
          {needsEmployeePicker ? (
            <FormField id="regularization-employee" label="Employee" required error={errors.employeeId}>
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

          <FormField
            id="regularization-date"
            label="Attendance date"
            required
            error={errors.attendanceDate}
          >
            <Input
              type="date"
              value={values.attendanceDate}
              disabled={Boolean(attendanceDate)}
              onChange={(e) => setValues((c) => ({ ...c, attendanceDate: e.target.value }))}
            />
          </FormField>

          <FormField id="regularization-type" label="Request type" required error={errors.requestType}>
            <NativeSelect
              value={values.requestType}
              onChange={(e) =>
                setValues((c) => ({
                  ...c,
                  requestType: e.target.value as RegularizationFormValues["requestType"],
                  correctionKind: e.target.value === "WRONG_SHIFT" ? "SHIFT" : c.correctionKind,
                }))
              }
            >
              <option value="">Choose…</option>
              {REGULARIZATION_TYPES.map((type) => (
                <option key={type} value={type}>
                  {REGULARIZATION_TYPE_LABELS[type]}
                </option>
              ))}
            </NativeSelect>
          </FormField>

          <FormField id="regularization-correction-kind" label="Correction" required>
            <NativeSelect
              value={values.correctionKind}
              onChange={(e) => updateCorrectionKind(e.target.value as RegularizationCorrectionKind)}
            >
              <option value="PUNCHES">Correct punch times</option>
              <option value="SHIFT">Correct the assigned shift</option>
            </NativeSelect>
          </FormField>

          {values.correctionKind === "SHIFT" ? (
            <FormField id="regularization-shift" label="Correct shift" required error={errors.shiftId}>
              <NativeSelect
                value={values.shiftId}
                onChange={(e) => setValues((c) => ({ ...c, shiftId: e.target.value }))}
              >
                <option value="">Choose…</option>
                {shifts.map((shift) => (
                  <option key={shift.id} value={shift.id}>
                    {shiftLabel(shift)}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          ) : (
            <div className="grid grid-cols-2 gap-4">
              <FormField id="regularization-punch-in" label="Check-in time" error={errors.punches}>
                <Input
                  type="time"
                  value={values.punchInTime}
                  onChange={(e) => setValues((c) => ({ ...c, punchInTime: e.target.value }))}
                />
              </FormField>
              <FormField id="regularization-punch-out" label="Check-out time">
                <Input
                  type="time"
                  value={values.punchOutTime}
                  onChange={(e) => setValues((c) => ({ ...c, punchOutTime: e.target.value }))}
                />
              </FormField>
            </div>
          )}

          <FormField
            id="regularization-reason"
            label="Reason"
            error={errors.reason}
            description="Explain what happened — required by most policies."
          >
            <Input
              value={values.reason}
              onChange={(e) => setValues((c) => ({ ...c, reason: e.target.value }))}
              maxLength={2000}
            />
          </FormField>

          <FormField
            id="regularization-attachment"
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
            {saving ? "Submitting…" : "Submit request"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
