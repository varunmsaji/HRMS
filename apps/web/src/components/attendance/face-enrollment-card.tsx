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
import { ApiError, describeApiError } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/attendance/format";
import { FACE_MAX_REFERENCE_PHOTOS, type FaceProfile } from "@/lib/attendance/types";
import { useAuth } from "@/lib/auth/auth-context";

const MAX_PHOTO_BYTES = 5 * 1024 * 1024;

type PhotoMode = "enroll" | "add";

interface FaceEnrollmentCardProps {
  employeeId: string;
  employeeLabel: string;
}

/** Enroll / extend / revoke an employee's face profile for face attendance. Rendered only for
 * callers holding `ATTENDANCE.FACE_ENROLLMENT_MANAGE`; the server still enforces scope. */
export function FaceEnrollmentCard({ employeeId, employeeLabel }: FaceEnrollmentCardProps) {
  const { user } = useAuth();
  const { toast } = useToast();
  const tz = user?.company_timezone ?? "Asia/Kolkata";

  const [profile, setProfile] = useState<FaceProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [photoMode, setPhotoMode] = useState<PhotoMode | null>(null);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [revoking, setRevoking] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setProfile(await apiClient.get<FaceProfile>(`/attendance/face-profiles/${employeeId}`));
    } catch (err) {
      if (err instanceof ApiError && err.code === "FACE_PROFILE_NOT_FOUND") {
        setProfile(null);
      } else {
        setLoadError(describeApiError(err));
      }
    } finally {
      setLoading(false);
    }
  }, [employeeId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleRevoke() {
    setRevoking(true);
    try {
      setProfile(await apiClient.delete<FaceProfile>(`/attendance/face-profiles/${employeeId}`));
      setRevokeOpen(false);
      toast({ title: "Face profile revoked", variant: "success" });
    } catch (err) {
      toast({ title: "Could not revoke face profile", description: describeApiError(err), variant: "danger" });
    } finally {
      setRevoking(false);
    }
  }

  const enrolled = profile?.status === "ENROLLED";
  const photosFull = (profile?.reference_photo_count ?? 0) >= FACE_MAX_REFERENCE_PHOTOS;

  return (
    <section
      aria-labelledby="face-enrollment-heading"
      className="flex flex-wrap items-center justify-between gap-4 rounded-md border border-border p-4"
    >
      <div className="flex items-start gap-3">
        <ScanFace aria-hidden className="mt-0.5 h-5 w-5 text-foreground-muted" />
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h3 id="face-enrollment-heading" className="text-sm font-semibold text-foreground">
              Face attendance
            </h3>
            {!loading && !loadError ? (
              enrolled ? (
                <Badge variant="success">Enrolled</Badge>
              ) : profile?.status === "REVOKED" ? (
                <Badge variant="warning">Revoked</Badge>
              ) : (
                <Badge variant="outline">Not enrolled</Badge>
              )
            ) : null}
          </div>
          <p className="text-sm text-foreground-secondary">
            {loading
              ? "Loading…"
              : loadError
                ? loadError
                : enrolled && profile
                  ? `Enrolled ${formatDateTime(profile.enrolled_at, tz)} · ${profile.reference_photo_count} of ${FACE_MAX_REFERENCE_PHOTOS} reference photos`
                  : profile?.status === "REVOKED" && profile.revoked_at
                    ? `Revoked ${formatDateTime(profile.revoked_at, tz)}. The face record was deleted from the verification service.`
                    : "Enroll a reference photo so this employee can punch in with their face."}
          </p>
        </div>
      </div>

      {!loading && !loadError ? (
        <div className="flex items-center gap-2">
          {enrolled ? (
            <>
              <Button
                type="button"
                variant="outline"
                disabled={photosFull}
                title={photosFull ? "Reference photo limit reached" : undefined}
                onClick={() => setPhotoMode("add")}
              >
                Add photo
              </Button>
              <Button type="button" variant="outline" onClick={() => setRevokeOpen(true)}>
                Revoke
              </Button>
            </>
          ) : (
            <Button type="button" onClick={() => setPhotoMode("enroll")}>
              {profile?.status === "REVOKED" ? "Re-enroll" : "Enroll face"}
            </Button>
          )}
        </div>
      ) : null}

      <FacePhotoDialog
        mode={photoMode}
        employeeId={employeeId}
        employeeLabel={employeeLabel}
        onClose={() => setPhotoMode(null)}
        onSaved={(saved) => {
          setProfile(saved);
          setPhotoMode(null);
        }}
      />

      <Dialog open={revokeOpen} onOpenChange={(next) => (!revoking ? setRevokeOpen(next) : null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Revoke face profile?</DialogTitle>
            <DialogDescription>
              {employeeLabel}&apos;s face record will be deleted from the verification service and
              they will no longer be able to punch in with their face. You can re-enroll them later.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={revoking} onClick={() => setRevokeOpen(false)}>
              Cancel
            </Button>
            <Button type="button" variant="destructive" disabled={revoking} onClick={() => void handleRevoke()}>
              {revoking ? "Revoking…" : "Revoke"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

interface FacePhotoDialogProps {
  mode: PhotoMode | null;
  employeeId: string;
  employeeLabel: string;
  onClose: () => void;
  onSaved: (profile: FaceProfile) => void;
}

function FacePhotoDialog({ mode, employeeId, employeeLabel, onClose, onSaved }: FacePhotoDialogProps) {
  const { toast } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (mode === null) {
      setFile(null);
      setConsent(false);
      setError(null);
    }
  }, [mode]);

  useEffect(() => {
    setPreviewUrl(null);
    if (!file) return;
    // A data: URL, not URL.createObjectURL — the CSP allows `img-src 'self' data:` only.
    let cancelled = false;
    const reader = new FileReader();
    reader.onload = () => {
      if (!cancelled && typeof reader.result === "string") setPreviewUrl(reader.result);
    };
    reader.readAsDataURL(file);
    return () => {
      cancelled = true;
      reader.abort();
    };
  }, [file]);

  function onFileChange(selected: File | undefined) {
    setError(null);
    if (!selected) {
      setFile(null);
      return;
    }
    if (!["image/jpeg", "image/png"].includes(selected.type)) {
      setError("Choose a JPEG or PNG photo.");
      setFile(null);
      return;
    }
    if (selected.size > MAX_PHOTO_BYTES) {
      setError("The photo must be 5 MB or smaller.");
      setFile(null);
      return;
    }
    setFile(selected);
  }

  async function handleSubmit() {
    if (!file || mode === null) return;
    setSaving(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.set("photo", file);
      let saved: FaceProfile;
      if (mode === "enroll") {
        formData.set("consent_confirmed", consent ? "true" : "false");
        saved = await apiClient.post<FaceProfile>(`/attendance/face-profiles/${employeeId}`, formData);
      } else {
        saved = await apiClient.post<FaceProfile>(`/attendance/face-profiles/${employeeId}/photos`, formData);
      }
      toast({ title: mode === "enroll" ? "Face enrolled" : "Reference photo added", variant: "success" });
      onSaved(saved);
    } catch (err) {
      setError(err instanceof ApiError && err.status < 500 ? err.message : describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  const canSubmit = Boolean(file) && (mode === "add" || consent) && !saving;

  return (
    <Dialog open={mode !== null} onOpenChange={(next) => (!next && !saving ? onClose() : null)}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{mode === "add" ? "Add reference photo" : "Enroll face"}</DialogTitle>
          <DialogDescription>
            A clear, front-facing photo of {employeeLabel} in good light, with no one else in frame.
            JPEG or PNG, up to 5 MB.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <input
            id="face-photo-input"
            type="file"
            accept="image/jpeg,image/png"
            capture="user"
            aria-label="Face photo"
            onChange={(e) => onFileChange(e.target.files?.[0])}
            className="block w-full text-sm text-foreground-secondary file:mr-3 file:rounded-md file:border file:border-border file:bg-surface-secondary file:px-3 file:py-1.5 file:text-sm file:text-foreground"
          />
          {previewUrl ? (
            // eslint-disable-next-line @next/next/no-img-element -- local data URL preview
            <img
              src={previewUrl}
              alt="Selected face photo preview"
              className="mx-auto max-h-56 rounded-md border border-border object-contain"
            />
          ) : null}

          {mode === "enroll" ? (
            <label className="flex items-start gap-2 text-sm text-foreground-secondary">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-input"
              />
              <span>
                {employeeLabel} has given consent for their face to be used for attendance
                verification. The time of this confirmation is recorded.
              </span>
            </label>
          ) : null}

          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" disabled={saving} onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" disabled={!canSubmit} onClick={() => void handleSubmit()}>
            {saving ? "Uploading…" : mode === "add" ? "Add photo" : "Enroll"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
