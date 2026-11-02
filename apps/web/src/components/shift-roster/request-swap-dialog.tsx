"use client";

import { useEffect, useState } from "react";

import { FormField } from "@/components/common/form-field";
import { useToast } from "@/components/common/toast";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import type { SwapCandidate } from "@/lib/shift-roster/schedule";

/** An employee asks a colleague to swap shifts on one day (`POST /v1/rosters/swap-requests/mine`).
 * The colleague then agrees and a manager approves. Only colleagues on a different published shift
 * that day are offered (`GET /v1/rosters/swap-candidates`). */
export function RequestSwapDialog({
  open,
  onOpenChange,
  today,
  onRequested,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  today: string;
  onRequested: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Request a shift swap</DialogTitle>
        </DialogHeader>
        {/* Mounted only while open, so every opening starts from a clean form. */}
        {open ? <SwapForm today={today} onClose={() => onOpenChange(false)} onRequested={onRequested} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function SwapForm({ today, onClose, onRequested }: { today: string; onClose: () => void; onRequested: () => void }) {
  const { toast } = useToast();
  const [date, setDate] = useState(today);
  const [loaded, setLoaded] = useState<{ date: string; rows: SwapCandidate[] } | null>(null);
  const [counterpartId, setCounterpartId] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Candidates belong to one day; an answer for another day counts as "still loading".
  const candidates = loaded?.date === date ? loaded.rows : null;

  useEffect(() => {
    let current = true;
    apiClient
      .get<SwapCandidate[]>(`/rosters/swap-candidates?swap_date=${date}`)
      .then((rows) => {
        if (current) setLoaded({ date, rows });
      })
      .catch(() => {
        if (current) setLoaded({ date, rows: [] });
      });
    return () => {
      current = false;
    };
  }, [date]);

  function changeDate(next: string) {
    setDate(next);
    setCounterpartId("");
  }

  async function submit() {
    if (!counterpartId) {
      setError("Choose a colleague to swap with.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await apiClient.post("/rosters/swap-requests/mine", {
        counterpart_employee_id: counterpartId,
        swap_date: date,
        reason: reason.trim() || null,
      });
      toast({ title: "Swap requested", description: "Your colleague needs to agree, then a manager approves.", variant: "success" });
      onClose();
      onRequested();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="space-y-4">
        <FormField id="swap-date" label="Day" description="You must both have a different published shift on this day.">
          <Input type="date" min={today} value={date} onChange={(e) => e.target.value && changeDate(e.target.value)} />
        </FormField>
        <FormField id="swap-with" label="Swap with">
          <NativeSelect value={counterpartId} onChange={(e) => setCounterpartId(e.target.value)} disabled={candidates === null}>
            <option value="">
              {candidates === null ? "Loading…" : candidates.length === 0 ? "No one available that day" : "Choose a colleague…"}
            </option>
            {(candidates ?? []).map((c) => (
              <option key={c.employee_id} value={c.employee_id}>
                {c.name} ({c.code}) · {c.shift_name}
              </option>
            ))}
          </NativeSelect>
        </FormField>
        <FormField id="swap-reason" label="Reason (optional)">
          <Textarea value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
        </FormField>
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        ) : null}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button type="button" onClick={() => void submit()} loading={saving} disabled={!counterpartId}>
          Send request
        </Button>
      </DialogFooter>
    </>
  );
}
