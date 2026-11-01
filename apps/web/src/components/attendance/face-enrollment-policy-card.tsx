"use client";

import { ScanFace } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { useToast } from "@/components/common/toast";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import type { FaceEnrollmentPolicy } from "@/lib/attendance/types";

const PATH = "/attendance/face-enrollment-policy";

/** Company setting: is face enrollment a required onboarding step? Policy only: it never marks
 * anyone enrolled, and existing employees are not locked out of attendance when it is turned on.
 * Rendered only for callers holding `ATTENDANCE.FACE_ENROLLMENT_MANAGE`; the server enforces it. */
export function FaceEnrollmentPolicyCard() {
  const { toast } = useToast();
  const [policy, setPolicy] = useState<FaceEnrollmentPolicy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setPolicy(await apiClient.get<FaceEnrollmentPolicy>(PATH));
    } catch (err) {
      setError(describeApiError(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggle(next: boolean) {
    setSaving(true);
    try {
      setPolicy(
        await apiClient.put<FaceEnrollmentPolicy>(PATH, { require_enrollment_on_onboarding: next }),
      );
      toast({ title: next ? "Face enrollment is now required in onboarding" : "Face enrollment is optional in onboarding", variant: "success" });
    } catch (err) {
      toast({ title: "Could not update the setting", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardContent className="space-y-3 pt-6">
        <div className="flex items-center gap-2">
          <ScanFace className="h-4 w-4 text-foreground-muted" aria-hidden="true" />
          <h3 className="text-sm font-medium text-foreground">Face enrollment during onboarding</h3>
        </div>
        {error ? (
          <p className="text-sm text-foreground-muted" role="alert">
            {error}
          </p>
        ) : (
          <label className="flex items-start gap-3 text-sm">
            <Checkbox
              checked={policy?.require_enrollment_on_onboarding ?? false}
              disabled={policy === null || saving}
              onChange={(e) => void toggle(e.target.checked)}
              aria-label="Require face enrollment during onboarding"
            />
            <span>
              <span className="font-medium text-foreground">Require face enrollment</span>
              <span className="block text-foreground-muted">
                When on, onboarding is not complete until the employee enrolls and HR approves.
                When off, employees can be onboarded without it and enroll later from the app.
              </span>
            </span>
          </label>
        )}
      </CardContent>
    </Card>
  );
}
