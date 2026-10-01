"use client";

import { ScanFace } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/attendance/format";
import type { FaceEnrollmentStatus, FaceEnrollmentWindow, FaceProfile } from "@/lib/attendance/types";
import { useAuth } from "@/lib/auth/auth-context";

interface FaceEnrollmentCardProps {
  employeeId: string;
  employeeLabel: string;
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

/** HR side of face enrollment: open a one-time self-enrollment window (the employee captures
 * their face in the mobile app), then approve or reject what they submitted. Rendered only for
 * callers holding `ATTENDANCE.FACE_ENROLLMENT_MANAGE`; the server still enforces scope. */
export function FaceEnrollmentCard({ employeeId, employeeLabel }: FaceEnrollmentCardProps) {
  const { user } = useAuth();
  const { toast } = useToast();
  const tz = user?.company_timezone ?? "Asia/Kolkata";
  const base = `/attendance/face-profiles/${employeeId}`;

  const [status, setStatus] = useState<FaceEnrollmentStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reviewPhoto, setReviewPhoto] = useState<string | null>(null);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectNote, setRejectNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setStatus(await apiClient.get<FaceEnrollmentStatus>(`${base}/enrollment`));
    } catch (err) {
      setLoadError(describeApiError(err));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    void load();
  }, [load]);

  const profile = status?.profile ?? null;
  const openWindowRow = status?.open_window ?? null;
  const pending = profile?.status === "PENDING_APPROVAL";

  useEffect(() => {
    setReviewPhoto(null);
    if (!pending || !profile?.has_review_photo) return;
    let cancelled = false;
    // Fetched through the API (auth + no-store) and shown as a data: URL — the CSP allows
    // `img-src 'self' data:` only, and the photo is never given a URL of its own.
    apiClient
      .download(`${base}/review-photo`)
      .then((file) => blobToDataUrl(file.blob))
      .then((url) => {
        if (!cancelled) setReviewPhoto(url);
      })
      .catch(() => {
        if (!cancelled) setReviewPhoto(null);
      });
    return () => {
      cancelled = true;
    };
  }, [base, pending, profile?.has_review_photo]);

  async function act(run: () => Promise<unknown>, success: string, failure: string) {
    setBusy(true);
    try {
      await run();
      toast({ title: success, variant: "success" });
      await load();
      return true;
    } catch (err) {
      toast({ title: failure, description: describeApiError(err), variant: "danger" });
      return false;
    } finally {
      setBusy(false);
    }
  }

  const openWindow = () =>
    act(
      () => apiClient.post<FaceEnrollmentWindow>(`${base}/enrollment-window`),
      "Face enrollment opened",
      "Could not open face enrollment",
    );
  const cancelWindow = () =>
    act(() => apiClient.delete(`${base}/enrollment-window`), "Face enrollment cancelled", "Could not cancel");
  const approve = () =>
    act(() => apiClient.post<FaceProfile>(`${base}/approve`), "Face profile approved", "Could not approve");
  async function reject() {
    const ok = await act(
      () => apiClient.post<FaceProfile>(`${base}/reject`, { note: rejectNote.trim() || null }),
      "Face profile rejected",
      "Could not reject",
    );
    if (ok) {
      setRejectOpen(false);
      setRejectNote("");
    }
  }
  async function revoke() {
    const ok = await act(() => apiClient.delete<FaceProfile>(base), "Face profile revoked", "Could not revoke");
    if (ok) setRevokeOpen(false);
  }

  let badge: React.ReactNode = null;
  let description = "";
  let actions: React.ReactNode = null;

  if (profile?.status === "ENROLLED") {
    badge = <Badge variant="success">Enrolled</Badge>;
    description = `Approved ${formatDateTime(profile.reviewed_at ?? profile.enrolled_at, tz)} · ${profile.reference_photo_count} reference angles`;
    actions = (
      <Button type="button" variant="outline" disabled={busy} onClick={() => setRevokeOpen(true)}>
        Revoke
      </Button>
    );
  } else if (pending && profile) {
    badge = <Badge variant="warning">Awaiting approval</Badge>;
    description = `Submitted ${formatDateTime(profile.enrolled_at, tz)} from the mobile app. Check that this is ${employeeLabel} before approving.`;
    actions = (
      <>
        <Button type="button" variant="outline" disabled={busy} onClick={() => setRejectOpen(true)}>
          Reject
        </Button>
        <Button type="button" disabled={busy} onClick={() => void approve()}>
          Approve
        </Button>
      </>
    );
  } else if (openWindowRow) {
    badge = <Badge variant="info">Enrollment open</Badge>;
    description = `${employeeLabel} can set up face attendance in the mobile app until ${formatDateTime(openWindowRow.expires_at, tz)}. The link closes once they finish.`;
    actions = (
      <Button type="button" variant="outline" disabled={busy} onClick={() => void cancelWindow()}>
        Cancel enrollment
      </Button>
    );
  } else {
    if (profile?.status === "REJECTED") {
      badge = <Badge variant="danger">Rejected</Badge>;
      description = `Rejected ${formatDateTime(profile.reviewed_at, tz)}. Open enrollment again to let them retry.${profile.review_note ? ` Reason: ${profile.review_note}` : ""}`;
    } else if (profile?.status === "REVOKED") {
      badge = <Badge variant="warning">Revoked</Badge>;
      description = `Revoked ${formatDateTime(profile.revoked_at, tz)}. The face record was deleted from the verification service.`;
    } else {
      badge = <Badge variant="outline">Not enrolled</Badge>;
      description = `Open a one-time enrollment so ${employeeLabel} can register their face from the mobile app.`;
    }
    actions = (
      <Button type="button" disabled={busy} onClick={() => void openWindow()}>
        Open face enrollment
      </Button>
    );
  }

  return (
    <section aria-labelledby="face-enrollment-heading" className="space-y-3 rounded-md border border-border p-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-start gap-3">
          <ScanFace aria-hidden className="mt-0.5 h-5 w-5 text-foreground-muted" />
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <h3 id="face-enrollment-heading" className="text-sm font-semibold text-foreground">
                Face attendance
              </h3>
              {!loading && !loadError ? badge : null}
            </div>
            <p className="text-sm text-foreground-secondary">
              {loading ? "Loading…" : loadError ? loadError : description}
            </p>
          </div>
        </div>
        {!loading && !loadError ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>

      {pending ? (
        reviewPhoto ? (
          // eslint-disable-next-line @next/next/no-img-element -- data URL of the photo under review
          <img
            src={reviewPhoto}
            alt={`Face submitted for ${employeeLabel}`}
            className="max-h-56 rounded-md border border-border object-contain"
          />
        ) : (
          <p className="text-sm text-foreground-muted">Loading submitted photo…</p>
        )
      ) : null}

      <Dialog open={rejectOpen} onOpenChange={(next) => (!busy ? setRejectOpen(next) : null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Reject face enrollment?</DialogTitle>
            <DialogDescription>
              The submitted face is deleted from the verification service. You can open enrollment
              again for {employeeLabel} afterwards.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1 text-sm">
            <label htmlFor="face-reject-note" className="text-foreground-secondary">
              Reason (shown to the employee, optional)
            </label>
            <textarea
              id="face-reject-note"
              value={rejectNote}
              onChange={(e) => setRejectNote(e.target.value)}
              maxLength={500}
              rows={3}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={busy} onClick={() => setRejectOpen(false)}>
              Cancel
            </Button>
            <Button type="button" variant="destructive" disabled={busy} onClick={() => void reject()}>
              {busy ? "Rejecting…" : "Reject"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={revokeOpen} onOpenChange={(next) => (!busy ? setRevokeOpen(next) : null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Revoke face profile?</DialogTitle>
            <DialogDescription>
              {employeeLabel}&apos;s face record will be deleted from the verification service and
              they will no longer be able to punch in with their face. You can open enrollment
              again later.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={busy} onClick={() => setRevokeOpen(false)}>
              Cancel
            </Button>
            <Button type="button" variant="destructive" disabled={busy} onClick={() => void revoke()}>
              {busy ? "Revoking…" : "Revoke"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
