import { useState } from "react";

import { FormField } from "@/components/common/form-field";
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
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import type { ShiftVersion } from "@/lib/shift/types";

interface ShiftPublishDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  shiftId: string;
  draft: ShiftVersion;
  /** The currently open PUBLISHED version, if any — its `version` becomes
   * `expected_previous_version`, the second concurrency token in the insert-new/close-previous
   * flow (mirrors `create_policy_assignment`, just with two rows mutated instead of one). */
  currentPublished: ShiftVersion | null;
  onPublished: (version: ShiftVersion) => void;
  onStale: (message: string) => void;
}

/** Publishing is the one action that makes a draft's schedule live and (if a previous version
 * is open) closes it out — `ShiftVersionOverlapError` (409, GiST-exclusion backstop) and
 * `STALE_RESOURCE` (either token) are real, expected outcomes here, not edge cases. */
export function ShiftPublishDialog({
  open,
  onOpenChange,
  shiftId,
  draft,
  currentPublished,
  onPublished,
  onStale,
}: ShiftPublishDialogProps) {
  const [reason, setReason] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handlePublish() {
    setPublishing(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { publish_reason: reason.trim() || null };
      if (currentPublished) body.expected_previous_version = currentPublished.version;

      const updated = await apiClient.post<ShiftVersion>(
        `/shifts/${shiftId}/versions/${draft.id}/publish`,
        body,
        { ifMatch: String(draft.version) },
      );
      onOpenChange(false);
      setReason("");
      onPublished(updated);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === "STALE_RESOURCE") {
        onOpenChange(false);
        onStale(
          currentPublished
            ? "This shift's published version was changed by someone else."
            : "This draft was changed by someone else.",
        );
        return;
      }
      setError(describeApiError(err));
    } finally {
      setPublishing(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (!publishing ? onOpenChange(next) : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Publish this schedule?</DialogTitle>
          <DialogDescription>
            {currentPublished
              ? `This closes the version currently effective from ${currentPublished.effective_from ?? "—"} and makes this one effective from ${draft.effective_from ?? "the date set above"}.`
              : "This makes the schedule live from the effective date set above. Published versions are immutable."}
          </DialogDescription>
        </DialogHeader>
        <FormField id="publish-reason" label="Reason (optional)">
          <Input value={reason} onChange={(e) => setReason(e.target.value)} />
        </FormField>
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={publishing}
          >
            Cancel
          </Button>
          <Button type="button" onClick={() => void handlePublish()} disabled={publishing}>
            {publishing ? "Publishing…" : "Publish"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
