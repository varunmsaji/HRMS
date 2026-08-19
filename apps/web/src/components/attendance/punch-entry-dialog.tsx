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
import { ApiError, describeApiError } from "@/lib/api/errors";
import type { Punch, PunchDirection } from "@/lib/attendance/types";

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

function nowForDatetimeLocal(): string {
  const now = new Date();
  now.setSeconds(0, 0);
  const offsetMs = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offsetMs).toISOString().slice(0, 16);
}

interface PunchEntryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pre-selects and locks the employee — used from the employee-scoped Attendance tab. Omit to
   * show a full employee picker (admin on-behalf punch from the team dashboard). */
  employeeId?: string;
  employeeLabel?: string;
  onRecorded: (punch: Punch) => void;
}

/** `POST /v1/attendance/punches` — self-punch when `employee_id` matches the caller, on-behalf
 * (`ATTENDANCE.PUNCH_ON_BEHALF`) otherwise; the router decides which, not this dialog (architecture
 * §23.2). Callers gate visibility of the "Record punch" action itself with `usePermissions`. */
export function PunchEntryDialog({
  open,
  onOpenChange,
  employeeId,
  employeeLabel: lockedLabel,
  onRecorded,
}: PunchEntryDialogProps) {
  const { toast } = useToast();
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [selectedEmployeeId, setSelectedEmployeeId] = useState(employeeId ?? "");
  const [direction, setDirection] = useState<PunchDirection>("IN");
  const [punchTime, setPunchTime] = useState(nowForDatetimeLocal());
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setSelectedEmployeeId(employeeId ?? "");
    setDirection("IN");
    setPunchTime(nowForDatetimeLocal());
    setReference("");
    setError(null);
    if (!employeeId) {
      void apiClient
        .get<EmployeeOption[]>("/employees")
        .then(setEmployees)
        .catch(() => setEmployees([]));
    }
  }, [open, employeeId]);

  async function handleSubmit() {
    if (!employeeId && !selectedEmployeeId) {
      setError("Choose an employee.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const punch = await apiClient.post<Punch>("/attendance/punches", {
        employee_id: employeeId ?? selectedEmployeeId,
        punch_time: new Date(punchTime).toISOString(),
        direction,
        reference: reference.trim() || undefined,
      });
      onRecorded(punch);
      onOpenChange(false);
      toast({ title: `${direction === "IN" ? "Punch in" : "Punch out"} recorded`, variant: "success" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError("You don't have permission to record this punch.");
        return;
      }
      setError(err instanceof ApiError ? describeApiError(err) : "Something went wrong.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (!saving ? onOpenChange(next) : null)}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Record punch</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          {employeeId ? (
            <FormField id="punch-employee-locked" label="Employee">
              <Input value={lockedLabel ?? employeeId} disabled />
            </FormField>
          ) : (
            <FormField id="punch-employee" label="Employee" required>
              <NativeSelect
                value={selectedEmployeeId}
                onChange={(e) => setSelectedEmployeeId(e.target.value)}
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
          <FormField id="punch-direction" label="Direction" required>
            <NativeSelect
              value={direction}
              onChange={(e) => setDirection(e.target.value as PunchDirection)}
            >
              <option value="IN">IN</option>
              <option value="OUT">OUT</option>
            </NativeSelect>
          </FormField>
          <FormField id="punch-time" label="Punch time" required>
            <Input
              type="datetime-local"
              value={punchTime}
              onChange={(e) => setPunchTime(e.target.value)}
            />
          </FormField>
          <FormField id="punch-reference" label="Reference" description="Optional note, e.g. a correction reason.">
            <Input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={200} />
          </FormField>
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void handleSubmit()} disabled={saving}>
            {saving ? "Recording…" : "Record punch"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
