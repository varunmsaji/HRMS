import { useEffect, useState } from "react";

import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { Shift, ShiftDeletionCheck } from "@/lib/shift/types";

const MIN_REASON_LENGTH = 10;

interface ShiftDeleteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  shift: Shift;
  onDeleted: () => void;
  onStale: () => void;
}

/** Permanent-removal flow with layered safeguards. The server is authoritative and re-checks
 * everything inside a locked transaction; this dialog just makes the consequences explicit:
 * 1. a live preflight lists every blocker (the delete button stays disabled while any exist),
 * 2. the shift's exact name must be typed back,
 * 3. a written reason (kept in the audit log) is required,
 * 4. an explicit "cannot be undone from the app" acknowledgement is required. */
export function ShiftDeleteDialog({
  open,
  onOpenChange,
  shift,
  onDeleted,
  onStale,
}: ShiftDeleteDialogProps) {
  const [check, setCheck] = useState<ShiftDeletionCheck | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [confirmName, setConfirmName] = useState("");
  const [reason, setReason] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [nameError, setNameError] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setCheck(null);
    setCheckError(null);
    setConfirmName("");
    setReason("");
    setAcknowledged(false);
    setNameError(undefined);
    setError(null);
    apiClient
      .get<ShiftDeletionCheck>(`/shifts/${shift.id}/deletion-check`)
      .then((data) => {
        if (!cancelled) setCheck(data);
      })
      .catch((err) => {
        if (!cancelled) setCheckError(describeApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [open, shift.id]);

  const nameMatches = confirmName === shift.name;
  const reasonValid = reason.trim().length >= MIN_REASON_LENGTH;
  const canSubmit =
    check?.can_delete === true &&
    nameMatches &&
    reasonValid &&
    acknowledged &&
    !deleting;

  async function handleDelete() {
    setDeleting(true);
    setError(null);
    setNameError(undefined);
    try {
      await apiClient.post(
        `/shifts/${shift.id}/delete`,
        {
          confirm_name: confirmName,
          reason: reason.trim(),
          acknowledge_irreversible: true,
        },
        { ifMatch: String(shift.version) },
      );
      onOpenChange(false);
      onDeleted();
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.status === 409 &&
        err.code === "STALE_RESOURCE"
      ) {
        onOpenChange(false);
        onStale();
        return;
      }
      if (
        err instanceof ApiError &&
        err.status === 409 &&
        err.code === "SHIFT_DELETE_BLOCKED"
      ) {
        // State changed since the preview (e.g. someone assigned it meanwhile) — refresh it.
        setCheck({
          can_delete: false,
          blockers: err.details.map((d) => ({
            code: d.code ?? "",
            message: d.message,
            count: 0,
          })),
          published_version_count: check?.published_version_count ?? 0,
          draft_version_count: check?.draft_version_count ?? 0,
        });
        return;
      }
      if (err instanceof ApiError && err.status === 422) {
        setNameError(getFieldError(err.details, "confirm_name"));
      }
      setError(describeApiError(err));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => (!deleting ? onOpenChange(next) : null)}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Delete shift “{shift.name}”?</DialogTitle>
          <DialogDescription>
            Deleting removes the shift and its schedule versions from every list
            and picker. It is only allowed for a shift that has never been used.
            Anything that has been assigned, rostered or used in attendance must
            be kept — deactivate it instead.
          </DialogDescription>
        </DialogHeader>

        {check === null && checkError === null ? (
          <LoadingState label="Checking whether this shift is in use…" />
        ) : null}
        {checkError ? (
          <p className="text-sm text-danger">{checkError}</p>
        ) : null}

        {check && !check.can_delete ? (
          <div
            className="rounded-md border border-danger/40 bg-danger/5 p-3 text-sm"
            role="alert"
          >
            <p className="font-medium text-danger">
              This shift can’t be deleted yet
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-foreground-secondary">
              {check.blockers.map((b) => (
                <li key={b.code}>{b.message}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {check?.can_delete ? (
          <div className="space-y-4">
            <div className="rounded-md border border-border bg-surface-secondary p-3 text-sm text-foreground-secondary">
              Not assigned to any employee, roster or attendance record.{" "}
              {check.published_version_count > 0
                ? `${check.published_version_count} published schedule version(s) and `
                : ""}
              {check.draft_version_count > 0
                ? `${check.draft_version_count} draft(s) `
                : ""}
              will be removed with it. The deletion is recorded in the audit
              log.
            </div>
            <FormField
              id="delete-confirm-name"
              label={`Type “${shift.name}” to confirm`}
              required
              error={nameError}
            >
              <Input
                value={confirmName}
                onChange={(e) => setConfirmName(e.target.value)}
                autoComplete="off"
              />
            </FormField>
            <FormField
              id="delete-reason"
              label="Reason for deletion"
              description={`At least ${MIN_REASON_LENGTH} characters. Saved in the audit log.`}
              required
            >
              <Textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </FormField>
            <label className="flex items-start gap-2 text-sm text-foreground">
              <Checkbox
                className="mt-0.5"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
              />
              <span>I understand this cannot be undone from the app.</span>
            </label>
          </div>
        ) : null}

        {error ? <p className="text-sm text-danger">{error}</p> : null}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={deleting}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => void handleDelete()}
            disabled={!canSubmit}
          >
            {deleting ? "Deleting…" : "Delete permanently"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
