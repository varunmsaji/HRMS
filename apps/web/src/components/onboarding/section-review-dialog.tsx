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
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { ONBOARDING_SECTION_LABELS, type OnboardingCaseDetail, type OnboardingSectionName } from "@/lib/onboarding/types";

interface SectionRejectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  caseId: string;
  section: OnboardingSectionName | null;
  onDone: (updatedCase: OnboardingCaseDetail) => void;
}

/** `POST /onboarding-cases/{caseId}/sections/{section}/review` with `status: "REJECTED"` — the
 * backend requires a non-empty `rejection_reason` for this status, mirroring
 * `DocumentRejectDialog`'s own shape exactly. Re-fetches the case afterward since the review
 * response is just the single section, not the whole case. */
export function SectionRejectDialog({
  open,
  onOpenChange,
  caseId,
  section,
  onDone,
}: SectionRejectDialogProps) {
  const { toast } = useToast();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleReject() {
    if (!section) return;
    if (!reason.trim()) {
      setError("A rejection reason is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await apiClient.post(`/onboarding-cases/${caseId}/sections/${section}/review`, {
        status: "REJECTED",
        rejection_reason: reason.trim(),
      });
      const updatedCase = await apiClient.get<OnboardingCaseDetail>(`/onboarding-cases/${caseId}`);
      onDone(updatedCase);
      onOpenChange(false);
      setReason("");
      toast({ title: "Section rejected", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        toast({ title: "You don't have permission to review this section", variant: "danger" });
        onOpenChange(false);
        return;
      }
      toast({ title: "Could not reject section", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (!saving ? onOpenChange(next) : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reject {section ? ONBOARDING_SECTION_LABELS[section] : ""}</DialogTitle>
          <DialogDescription>The candidate will be asked to fix and resubmit this section.</DialogDescription>
        </DialogHeader>
        <FormField id="sectionRejectionReason" label="Reason" required error={error ?? undefined}>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} />
        </FormField>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button type="button" variant="destructive" onClick={() => void handleReject()} disabled={saving}>
            {saving ? "Rejecting…" : "Reject"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
