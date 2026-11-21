"use client";

import { AlertTriangle } from "lucide-react";
import { useState } from "react";

import { useToast } from "@/components/common/toast";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";

/** The API takes at most this many employees in one range request. */
export const RECALCULATE_MAX_EMPLOYEES = 1000;

interface Props {
  /** The focus date, `YYYY-MM-DD`, a day that has already passed. */
  date: string;
  /** How the date reads in the page ("Mon 10 Aug"). */
  dateLabel: string;
  /** Employed people with no calculated day on that date. */
  employeeIds: string[];
  /** Whether the viewer may queue a recalculation (`ATTENDANCE.RECOMPUTE`). */
  canRecalculate: boolean;
  /** Runs after the request was queued, so the page can reload when the work is done. */
  onQueued?: () => void;
}

/** R-D06 — a past date on which some employed people have no calculated day. They would be
 * missing from every figure, and at period close an unresolved day becomes absent, so HR is told
 * and can queue the calculation instead of finding out at payroll. */
export function NotCalculatedNotice({ date, dateLabel, employeeIds, canRecalculate, onQueued }: Props) {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  if (employeeIds.length === 0) return null;

  const tooMany = employeeIds.length > RECALCULATE_MAX_EMPLOYEES;
  async function recalculate() {
    setBusy(true);
    try {
      await apiClient.post("/attendance/days/calculate-range", {
        date_from: date,
        date_to: date,
        employee_ids: employeeIds,
      });
      toast({
        title: "Calculation queued",
        description: `${employeeIds.length} ${employeeIds.length === 1 ? "day" : "days"} for ${dateLabel}. Refresh in a minute to see them counted.`,
        variant: "success",
      });
      onQueued?.();
    } catch (err) {
      toast({ title: "Could not queue the calculation", description: describeApiError(err), variant: "danger" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="note" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-warning-border bg-warning-subtle p-3 text-sm text-foreground">
      <p className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <span>
          <span className="font-medium">Not calculated: {employeeIds.length}.</span>{" "}
          {employeeIds.length === 1 ? "One employed person has" : `${employeeIds.length} employed people have`} no calculated day for{" "}
          {dateLabel}, so they are missing from the figures below.
        </span>
      </p>
      {canRecalculate && !tooMany ? (
        <Button size="sm" variant="outline" onClick={() => void recalculate()} disabled={busy}>
          {busy ? "Queuing…" : "Recalculate"}
        </Button>
      ) : null}
    </div>
  );
}
