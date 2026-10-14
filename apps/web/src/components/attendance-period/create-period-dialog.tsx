"use client";

import { useState } from "react";

import { FormField } from "@/components/common/form-field";
import { useToast } from "@/components/common/toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import type { AttendancePeriod, AttendancePeriodCreatePayload } from "@/lib/attendance-period/types";
import type { LegalEntity } from "@/lib/legal-entity/types";

interface CreatePeriodDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (period: AttendancePeriod) => void;
  legalEntities: LegalEntity[];
}

type Cycle = "MONTH" | "CUSTOM";

/** `POST /v1/attendance-periods` (architecture §4.2/§22, decision log WD-30). Creating a period
 * opens it immediately — there is no separate "open" step. Each company runs its own cycle
 * (decision 14); the backend rejects a range overlapping another period of the same entity
 * (`ATTENDANCE_PERIOD_OVERLAP`). A full calendar month is the default (decision 18); a custom
 * range stays available for an off-cycle period. */
export function CreatePeriodDialog({
  open,
  onOpenChange,
  onCreated,
  legalEntities,
}: CreatePeriodDialogProps) {
  const { user } = useAuth();
  const { toast } = useToast();
  // `SR-06` (execution gate §21, Phase 4) — was `todayIso()`, the UTC calendar date, PERSISTED
  // straight into `period_start`/`period_end`. Between 00:00 and 05:29 IST that pre-filled a
  // payroll period boundary one day early — not just a display glitch, a wrong value written to
  // a record HR then finalizes and locks.
  const today = () => businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const defaultEntityId = () => (legalEntities.length === 1 ? legalEntities[0].id : "");
  const [legalEntityId, setLegalEntityId] = useState(defaultEntityId);
  const [cycle, setCycle] = useState<Cycle>("MONTH");
  const [month, setMonth] = useState(() => today().slice(0, 7));
  const [periodStart, setPeriodStart] = useState(today);
  const [periodEnd, setPeriodEnd] = useState(today);
  const [label, setLabel] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function reset() {
    setLegalEntityId(defaultEntityId());
    setCycle("MONTH");
    setMonth(today().slice(0, 7));
    setPeriodStart(today());
    setPeriodEnd(today());
    setLabel("");
    setFormError(null);
  }

  async function handleCreate() {
    const entityId = legalEntityId || defaultEntityId();
    if (!entityId) {
      setFormError("Choose a company.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const payload: AttendancePeriodCreatePayload = {
        legal_entity_id: entityId,
        ...(cycle === "MONTH"
          ? { month }
          : { period_start: periodStart, period_end: periodEnd }),
        label: label.trim() || undefined,
      };
      const created = await apiClient.post<AttendancePeriod>("/attendance-periods", payload);
      onCreated(created);
      onOpenChange(false);
      reset();
      toast({ title: "Attendance period created", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError && err.code === "ATTENDANCE_PERIOD_OVERLAP") {
        setFormError("Another period for this company already covers part of these dates.");
        return;
      }
      setFormError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (saving) return;
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New attendance period</DialogTitle>
          <DialogDescription>
            The period opens immediately — attendance for these dates stays fully editable until
            you finalize it. Each company closes its own period.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <FormField id="period-legal-entity" label="Company">
            <NativeSelect
              value={legalEntityId || defaultEntityId()}
              onChange={(e) => setLegalEntityId(e.target.value)}
            >
              {legalEntities.length !== 1 ? <option value="">Select a company</option> : null}
              {legalEntities.map((entity) => (
                <option key={entity.id} value={entity.id}>
                  {entity.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id="period-cycle" label="Cycle">
            <NativeSelect
              value={cycle}
              onChange={(e) => setCycle(e.target.value as Cycle)}
            >
              <option value="MONTH">Calendar month</option>
              <option value="CUSTOM">Custom date range</option>
            </NativeSelect>
          </FormField>
          {cycle === "MONTH" ? (
            <FormField id="period-month" label="Month" description="1st to last day of the month.">
              <Input
                type="month"
                value={month}
                onChange={(e) => setMonth(e.target.value)}
              />
            </FormField>
          ) : (
            <>
              <FormField id="period-start" label="Period start">
                <Input
                  type="date"
                  value={periodStart}
                  onChange={(e) => setPeriodStart(e.target.value)}
                />
              </FormField>
              <FormField id="period-end" label="Period end">
                <Input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
              </FormField>
            </>
          )}
          <FormField
            id="period-label"
            label="Label"
            description={
              cycle === "MONTH"
                ? 'Optional — defaults to the month name, e.g. "August 2026".'
                : 'Optional, e.g. "August 2026".'
            }
          >
            <Input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={100} />
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
          <Button type="button" onClick={() => void handleCreate()} disabled={saving}>
            {saving ? "Creating…" : "Create period"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
