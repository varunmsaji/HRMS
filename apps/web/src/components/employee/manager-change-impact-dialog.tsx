"use client";

import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ManagerChangeImpact } from "@/lib/employee/types";

interface ManagerChangeImpactDialogProps {
  open: boolean;
  impact: ManagerChangeImpact | null;
  /** The impact changed after the user last saw it; they must review the new figures. */
  stale: boolean;
  submitting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ManagerChangeImpactDialog({
  open,
  impact,
  stale,
  submitting,
  onCancel,
  onConfirm,
}: ManagerChangeImpactDialogProps) {
  const rows: Array<[string, number]> = impact
    ? [
        ["Leave requests", impact.requests.leave],
        ["Attendance corrections", impact.requests.attendance_regularization],
        ["Overtime requests", impact.requests.overtime],
      ]
    : [];

  return (
    <Dialog open={open} onOpenChange={(next) => (!next && !submitting ? onCancel() : null)}>
      <DialogContent className="max-w-lg" data-testid="manager-change-impact-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-amber-600" aria-hidden="true" />
            Pending approval requests
          </DialogTitle>
          <DialogDescription>
            This employee has pending requests that may be affected by this manager change.
          </DialogDescription>
        </DialogHeader>

        {stale ? (
          <p role="alert" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            The pending requests changed while you were reviewing this change. Please review the
            updated impact before continuing.
          </p>
        ) : null}

        <div className="space-y-3 text-sm text-foreground">
          <p>
            Changing the reporting manager will <strong>not</strong> change the approver for
            existing pending requests. Existing pending requests will remain with their current
            resolved approver. Future requests will follow the applicable reporting-manager and
            effective-date rules.
          </p>
          <dl className="divide-y divide-border rounded-md border border-border" aria-label="Pending requests by type">
            {rows.map(([label, count]) => (
              <div key={label} className="flex items-center justify-between px-3 py-2">
                <dt>{label}</dt>
                <dd className="font-medium tabular-nums">{count}</dd>
              </div>
            ))}
            <div className="flex items-center justify-between bg-muted/40 px-3 py-2 font-semibold">
              <dt>Total pending requests</dt>
              <dd className="tabular-nums" data-testid="impact-total">
                {impact?.total_pending_requests ?? 0}
              </dd>
            </div>
          </dl>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button type="button" variant="destructive" onClick={onConfirm} disabled={submitting || !impact}>
            {submitting ? "Changing Manager…" : "Change Manager Anyway"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
