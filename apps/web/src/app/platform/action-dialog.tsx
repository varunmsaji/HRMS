"use client";

import { useState } from "react";

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
import { Label } from "@/components/ui/label";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { platformApi } from "@/lib/platform/api";

export type DialogAction = "approve" | "reject" | "suspend" | "reactivate" | "terminate";

export const ACTION_COPY: Record<
  DialogAction,
  { label: string; help: string; reasonRequired: boolean; destructive?: boolean }
> = {
  approve: { label: "Approve", help: "Starts the trial and gives the company full access.", reasonRequired: false },
  reject: { label: "Reject", help: "The company is told why and can no longer sign in.", reasonRequired: true, destructive: true },
  suspend: { label: "Suspend", help: "Read-only grace mode: users can sign in and view data, but cannot change anything.", reasonRequired: true, destructive: true },
  reactivate: { label: "Reactivate", help: "Restores full access.", reasonRequired: false },
  terminate: { label: "Terminate", help: "Closes the company. Nobody can sign in; data is kept for the retention period.", reasonRequired: true, destructive: true },
};

/** Shared confirm dialog for a lifecycle action (dashboard queue and company detail page). The
 * reason is mandatory where the API requires it; terminate also asks for the company name. */
export function ActionDialog({
  company,
  action,
  onClose,
  onDone,
}: {
  company: { id: string; name: string };
  action: DialogAction;
  onClose: () => void;
  onDone: () => void;
}) {
  const copy = ACTION_COPY[action];
  const [reason, setReason] = useState("");
  const [confirmName, setConfirmName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit =
    !busy &&
    (!copy.reasonRequired || reason.trim().length >= 3) &&
    (action !== "terminate" || confirmName === company.name);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {};
      if (reason.trim()) body.reason = reason.trim();
      if (action === "terminate") body.confirm_name = confirmName;
      await platformApi.act(company.id, action, body);
      onDone();
    } catch (e) {
      const detail =
        e instanceof ApiError
          ? (getFieldError(e.details, "reason") ?? getFieldError(e.details, "confirm_name"))
          : undefined;
      setError(detail ?? describeApiError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{copy.label} {company.name}</DialogTitle>
          <DialogDescription>{copy.help}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="reason">Reason{copy.reasonRequired ? "" : " (optional)"}</Label>
            <Input id="reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
            {copy.reasonRequired ? <p className="text-xs text-foreground-muted">Shown to the company admin and kept in the audit log.</p> : null}
          </div>
          {action === "terminate" ? (
            <div className="space-y-1.5">
              <Label htmlFor="confirm">Type the company name to confirm</Label>
              <Input id="confirm" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} />
            </div>
          ) : null}
          {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button variant={copy.destructive ? "destructive" : "default"} disabled={!canSubmit} onClick={submit}>
            {busy ? "Working…" : copy.label}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
