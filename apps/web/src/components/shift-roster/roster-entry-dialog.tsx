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
import type { ShiftRoster } from "@/lib/shift-roster/types";
import {
  buildCreatePayload,
  buildUpdatePatch,
  emptyRosterFormValues,
  rosterToFormValues,
  validateRosterForm,
  type RosterDayKind,
  type RosterFormErrors,
  type RosterFormValues,
} from "@/lib/shift-roster/validate-shift-roster";

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

function employeeLabel(employee: EmployeeOption): string {
  const name = [employee.first_name, employee.last_name].filter(Boolean).join(" ");
  return employee.employee_code ? `${name} (${employee.employee_code})` : name;
}

function shiftLabel(shift: ShiftOption): string {
  return shift.code ? `${shift.name} (${shift.code})` : shift.name;
}

interface RosterEntryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Present to edit/publish an existing roster row; absent to create a new one. */
  roster?: ShiftRoster | null;
  /** Pre-fills and locks the employee/date for a "create for this cell" flow (Roster Calendar). */
  employeeId?: string;
  employeeLabel?: string;
  rosterDate?: string;
  onSaved: (roster: ShiftRoster) => void;
}

/** `POST /v1/rosters` (create, always DRAFT) / `PATCH /v1/rosters/{id}` (edit) /
 * `POST /v1/rosters/{id}/publish` (DRAFT -> PUBLISHED, WD-27). Mirrors `PunchEntryDialog`'s
 * shape. `dayKind` collapses `shift_id`/`is_week_off_override`/`is_holiday_working_override`
 * into one choice so the form can never submit an invalid combination
 * (`shift_roster_override_exclusive_check`). */
export function RosterEntryDialog({
  open,
  onOpenChange,
  roster,
  employeeId,
  employeeLabel: lockedEmployeeLabel,
  rosterDate,
  onSaved,
}: RosterEntryDialogProps) {
  const { toast } = useToast();
  const isEdit = Boolean(roster);

  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [shifts, setShifts] = useState<ShiftOption[]>([]);
  const [values, setValues] = useState<RosterFormValues>(() => emptyRosterFormValues());
  const [errors, setErrors] = useState<RosterFormErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);

  useEffect(() => {
    if (!open) return;
    setValues(
      roster
        ? rosterToFormValues(roster)
        : emptyRosterFormValues({ employeeId: employeeId ?? "", rosterDate: rosterDate ?? "" }),
    );
    setErrors({});
    setFormError(null);
    if (!employeeId && !roster) {
      void apiClient
        .get<EmployeeOption[]>("/employees")
        .then(setEmployees)
        .catch(() => setEmployees([]));
    }
    void apiClient
      .get<ShiftOption[]>("/shifts")
      .then(setShifts)
      .catch(() => setShifts([]));
  }, [open, roster, employeeId, rosterDate]);

  function updateDayKind(dayKind: RosterDayKind) {
    setValues((current) => ({ ...current, dayKind }));
  }

  async function handleSave() {
    const clientErrors = validateRosterForm(values);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }
    setSaving(true);
    setErrors({});
    setFormError(null);
    try {
      const saved = roster
        ? await apiClient.patch<ShiftRoster>(`/rosters/${roster.id}`, buildUpdatePatch(values), {
            ifMatch: String(roster.version),
          })
        : await apiClient.post<ShiftRoster>("/rosters", buildCreatePayload(values));
      onSaved(saved);
      onOpenChange(false);
      toast({
        title: roster ? "Roster entry updated" : "Roster entry added as draft",
        variant: "success",
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setErrors({ shiftId: getFieldError(err.details, "shift_id") });
        setFormError(describeApiError(err));
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setFormError("You don't have permission to manage rosters for this employee.");
        return;
      }
      setFormError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  async function handlePublish() {
    if (!roster) return;
    setPublishing(true);
    setFormError(null);
    try {
      const published = await apiClient.post<ShiftRoster>(
        `/rosters/${roster.id}/publish`,
        {},
        { ifMatch: String(roster.version) },
      );
      onSaved(published);
      onOpenChange(false);
      toast({ title: "Roster entry published", variant: "success" });
    } catch (err) {
      setFormError(describeApiError(err));
    } finally {
      setPublishing(false);
    }
  }

  const busy = saving || publishing;

  return (
    <Dialog open={open} onOpenChange={(next) => (!busy ? onOpenChange(next) : null)}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{roster ? "Edit roster entry" : "Add roster entry"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          {employeeId || roster ? (
            <FormField id="roster-employee-locked" label="Employee">
              <Input value={lockedEmployeeLabel ?? values.employeeId} disabled />
            </FormField>
          ) : (
            <FormField id="roster-employee" label="Employee" required error={errors.employeeId}>
              <NativeSelect
                value={values.employeeId}
                onChange={(e) => setValues((c) => ({ ...c, employeeId: e.target.value }))}
              >
                <option value="">Choose…</option>
                {employees.map((emp) => (
                  <option key={emp.id} value={emp.id}>
                    {employeeLabel(emp)}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          )}

          <FormField id="roster-date" label="Date" required error={errors.rosterDate}>
            <Input
              type="date"
              value={values.rosterDate}
              disabled={Boolean(rosterDate) || isEdit}
              onChange={(e) => setValues((c) => ({ ...c, rosterDate: e.target.value }))}
            />
          </FormField>

          <FormField id="roster-day-kind" label="Day type" required>
            <NativeSelect
              value={values.dayKind}
              onChange={(e) => updateDayKind(e.target.value as RosterDayKind)}
            >
              <option value="SHIFT">Assign a shift</option>
              <option value="WEEK_OFF">Week off (overrides the calendar)</option>
              <option value="HOLIDAY_WORKING">Working holiday (overrides the calendar)</option>
            </NativeSelect>
          </FormField>

          {values.dayKind === "SHIFT" ? (
            <FormField id="roster-shift" label="Shift" required error={errors.shiftId}>
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
          ) : null}

          {values.dayKind === "HOLIDAY_WORKING" ? (
            <FormField
              id="roster-shift-optional"
              label="Shift (optional)"
              description="Leave blank if this employee's working hours on the holiday aren't scheduled."
            >
              <NativeSelect
                value={values.shiftId}
                onChange={(e) => setValues((c) => ({ ...c, shiftId: e.target.value }))}
              >
                <option value="">No shift</option>
                {shifts.map((shift) => (
                  <option key={shift.id} value={shift.id}>
                    {shiftLabel(shift)}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          ) : null}

          <FormField
            id="roster-reason"
            label="Reason"
            description="Optional note — recorded on the audit trail."
          >
            <Input
              value={values.reason}
              onChange={(e) => setValues((c) => ({ ...c, reason: e.target.value }))}
              maxLength={500}
            />
          </FormField>

          {roster ? (
            <p className="text-xs text-foreground-muted">
              Status: <span className="font-medium">{roster.status}</span>
              {roster.status === "DRAFT"
                ? " — not yet visible to attendance calculation."
                : " — live for attendance calculation."}
            </p>
          ) : (
            <p className="text-xs text-foreground-muted">
              New entries start as a draft and won&apos;t affect attendance until published.
            </p>
          )}

          {formError ? (
            <p role="alert" className="text-sm text-danger">
              {formError}
            </p>
          ) : null}
        </div>
        <DialogFooter className="gap-2 sm:justify-between">
          <div>
            {roster && roster.status === "DRAFT" ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => void handlePublish()}
                disabled={busy}
              >
                {publishing ? "Publishing…" : "Publish"}
              </Button>
            ) : null}
          </div>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleSave()} disabled={busy}>
              {saving ? "Saving…" : roster ? "Save changes" : "Add as draft"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
