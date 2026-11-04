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
import { describeApiError } from "@/lib/api/errors";

export interface EndTarget {
  assignmentId: string;
  version: number;
  effectiveFrom: string;
  description: string;
}

/** Mount with a `key` per target so the date starts fresh each time. */
export function EndAssignmentDialog({
  target,
  today,
  onClose,
  onEnded,
}: {
  target: EndTarget;
  today: string;
  onClose: () => void;
  onEnded: () => void;
}) {
  const { toast } = useToast();
  const [lastDay, setLastDay] = useState(today < target.effectiveFrom ? target.effectiveFrom : today);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleEnd() {
    if (!lastDay) {
      setError("Last day is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await apiClient.post(
        `/policy-assignments/${target.assignmentId}/end`,
        { effective_to: lastDay },
        { ifMatch: String(target.version) },
      );
      toast({ title: "Assignment ended", variant: "success" });
      onEnded();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => (!open && !saving ? onClose() : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>End this assignment?</DialogTitle>
          <DialogDescription>
            {target.description}. After the last day, these people follow the next wider assignment,
            ending at the company-wide one.
          </DialogDescription>
        </DialogHeader>
        <FormField id="end-assignment-date" label="Last day" required>
          <Input
            type="date"
            min={target.effectiveFrom}
            value={lastDay}
            onChange={(e) => setLastDay(e.target.value)}
          />
        </FormField>
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => void handleEnd()}
            disabled={saving}
          >
            {saving ? "Ending…" : "End assignment"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
