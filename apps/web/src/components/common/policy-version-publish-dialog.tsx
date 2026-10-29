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
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import { ApiError, describeApiError } from "@/lib/api/errors";

interface VersionLike {
  id: string;
  version: number;
  effective_from: string | null;
}

interface PolicyVersionPublishDialogProps<T extends VersionLike> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** e.g. `/attendance-policies/{policyId}/versions` */
  versionsPath: string;
  draft: T;
  currentPublished: T | null;
  onPublished: (version: T) => void;
  onStale: (message: string) => void;
}

/** Shared publish dialog for all three W3 policy families (Attendance/Overtime/Regularization) —
 * identical insert-new/close-previous flow to `ShiftPublishDialog` (two concurrency tokens: the
 * draft's own `If-Match`, and `expected_previous_version` for the currently open published row),
 * generalised here instead of tripled since only the URL and version shape differ. */
export function PolicyVersionPublishDialog<T extends VersionLike>({
  open,
  onOpenChange,
  versionsPath,
  draft,
  currentPublished,
  onPublished,
  onStale,
}: PolicyVersionPublishDialogProps<T>) {
  const datePattern = useCompanyDatePattern();
  const [reason, setReason] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handlePublish() {
    setPublishing(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { publish_reason: reason.trim() || null };
      if (currentPublished) body.expected_previous_version = currentPublished.version;

      const updated = await apiClient.post<T>(`${versionsPath}/${draft.id}/publish`, body, {
        ifMatch: String(draft.version),
      });
      onOpenChange(false);
      setReason("");
      onPublished(updated);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === "STALE_RESOURCE") {
        onOpenChange(false);
        onStale(
          currentPublished
            ? "The currently published version was changed by someone else."
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
          <DialogTitle>Publish this version?</DialogTitle>
          <DialogDescription>
            {currentPublished
              ? `This closes the version currently effective from ${currentPublished.effective_from ? formatCompanyDate(currentPublished.effective_from, datePattern) : "—"} and makes this one effective from ${draft.effective_from ? formatCompanyDate(draft.effective_from, datePattern) : "the date set above"}. Published versions are immutable.`
              : "This makes the policy live from the effective date set above. Published versions are immutable — a correction requires a new draft."}
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
