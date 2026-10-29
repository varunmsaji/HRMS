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
import { nowInZoneForDatetimeLocal, wallTimeToUtcIso, zoneLabel } from "@/lib/attendance/format";
import type { Punch, PunchDirection } from "@/lib/attendance/types";
import { useAuth } from "@/lib/auth/auth-context";

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

interface PunchEntryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pre-selects and locks the employee — used from the employee-scoped Attendance tab. Omit to
   * show a full employee picker (admin on-behalf punch from the team dashboard). */
  employeeId?: string;
  employeeLabel?: string;
  onRecorded: (punch: Punch) => void;
}

/** Two distinct request shapes, chosen by mode — never one endpoint that infers the act from the
 * body (`DEC-TZ-01`/`ED-4`, SELECTED):
 *
 * - **Self mode** — the target employee is the caller's own (`employeeId === user.employee_id`,
 *   or no employee is pre-selected at all and the caller picks themselves). Posts to
 *   `POST /v1/attendance/punches/me` with `{direction, reference?}` — **no time field is shown or
 *   sent**. The server stamps the instant at receipt; a client clock can no longer set an
 *   employee's own attendance time.
 * - **Admin/on-behalf mode** — any other target employee. Posts to `POST /v1/attendance/punches`
 *   with `{employee_id, direction, punch_time, reference}` — a specific time and a reason are
 *   both required, because this path exists to record an instant the server did not itself
 *   observe. The time field is a bare `datetime-local` value (no zone of its own) labelled with
 *   the resolved business timezone (`punchTz`); `wallTimeToUtcIso`/`nowInZoneForDatetimeLocal`
 *   (`@/lib/attendance/format`) interpret and seed it explicitly in that zone, never the admin's
 *   own browser zone (`D1`, staging validation report — the label used to promise IST while
 *   `new Date(punchTime).toISOString()` silently read the viewer's own clock instead).
 *
 * Callers gate visibility of the "Record punch" action itself with `usePermissions`. */
export function PunchEntryDialog({
  open,
  onOpenChange,
  employeeId,
  employeeLabel: lockedLabel,
  onRecorded,
}: PunchEntryDialogProps) {
  const { toast } = useToast();
  const { user } = useAuth();
  // `DEC-TZ-02`/`D1` — the on-behalf punch instant is always interpreted in the resolved business
  // timezone, never the admin's own browser zone. Falls back to `Asia/Kolkata`, matching every
  // other `user?.company_timezone ?? "Asia/Kolkata"` call site in this module (e.g.
  // `employee-attendance-panel.tsx`).
  const punchTz = user?.company_timezone ?? "Asia/Kolkata";
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [selectedEmployeeId, setSelectedEmployeeId] = useState(employeeId ?? "");
  const [direction, setDirection] = useState<PunchDirection>("IN");
  const [punchTime, setPunchTime] = useState(() => nowInZoneForDatetimeLocal(punchTz));
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const targetEmployeeId = employeeId ?? selectedEmployeeId;
  const isSelf = targetEmployeeId !== "" && targetEmployeeId === user?.employee_id;

  useEffect(() => {
    if (!open) return;
    setSelectedEmployeeId(employeeId ?? "");
    setDirection("IN");
    setPunchTime(nowInZoneForDatetimeLocal(punchTz));
    setReference("");
    setError(null);
    if (!employeeId) {
      void apiClient
        .getList<EmployeeOption>("/employees", { per_page: 100 })
        .then(({ data }) => setEmployees(data))
        .catch(() => setEmployees([]));
    }
  }, [open, employeeId, punchTz]);

  async function handleSubmit() {
    if (!employeeId && !selectedEmployeeId) {
      setError("Choose an employee.");
      return;
    }
    if (!isSelf && !reference.trim()) {
      setError("A reason is required for an on-behalf punch.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const punch = isSelf
        ? await apiClient.post<Punch>("/attendance/punches/me", {
            direction,
            reference: reference.trim() || undefined,
          })
        : await apiClient.post<Punch>("/attendance/punches", {
            employee_id: targetEmployeeId,
            // `D1` — `punchTime` is a bare `datetime-local` wall-clock string with no zone of its
            // own; `wallTimeToUtcIso` interprets it explicitly as `punchTz`, never the browser's
            // own zone (`new Date(punchTime).toISOString()` would have done that instead).
            punch_time: wallTimeToUtcIso(punchTime, punchTz),
            direction,
            reference: reference.trim(),
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
          {isSelf ? (
            <p className="text-sm text-foreground-secondary">
              Recorded at the current time — self-service punches can no longer be backdated or
              set from your device&rsquo;s clock.
            </p>
          ) : (
            <FormField id="punch-time" label={`Punch time (${zoneLabel(punchTz)})`} required>
              <Input
                type="datetime-local"
                value={punchTime}
                onChange={(e) => setPunchTime(e.target.value)}
              />
            </FormField>
          )}
          <FormField
            id="punch-reference"
            label="Reference"
            required={!isSelf}
            description={
              isSelf
                ? "Optional note."
                : "Required — the reason for this on-behalf correction, kept in the audit log."
            }
          >
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
