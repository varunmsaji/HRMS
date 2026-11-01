"use client";

import { ScanFace, Smartphone } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import {
  FACE_ENROLLMENT_STATE_LABEL,
  type FaceEnrollmentState,
  type FaceEnrollmentStatus,
} from "@/lib/attendance/types";

const GUIDANCE: Record<FaceEnrollmentState, string> = {
  NOT_ENROLLED: "Your HR team has not opened face enrollment for you yet.",
  ENROLLMENT_AVAILABLE:
    "Face enrollment is open. Open the Krewoxa mobile app and tap Start Enrollment to capture your face.",
  PENDING_APPROVAL: "Your face capture was submitted and is waiting for HR approval.",
  ENROLLED: "Your face is enrolled. You can use face verification when you punch.",
  REJECTED: "Your last enrollment was rejected. Ask HR to open enrollment again.",
  REVOKED: "Your face enrollment was revoked. Ask HR to open enrollment again.",
};

/** Landing page for the "Face Enrollment Requested" notification. It shows the canonical status
 * from the server (the notification itself carries none); the capture happens in the mobile app. */
export default function FaceSetupPage() {
  const [status, setStatus] = useState<FaceEnrollmentStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      setStatus(await apiClient.get<FaceEnrollmentStatus>("/attendance/face-enrollment/me"));
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Fetch-on-mount: the loader sets its own loading/error state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const state = status?.enrollment_state;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Face Attendance Setup"
        description="Enroll your face so you can punch in with face verification."
      />
      {loading ? (
        <LoadingState />
      ) : error || !state ? (
        <ErrorState message="Couldn’t load your enrollment status." onRetry={() => void load()} />
      ) : (
        <Card>
          <CardContent className="flex items-start gap-4 p-6">
            <ScanFace className="mt-0.5 h-6 w-6 text-foreground-muted" aria-hidden="true" />
            <div className="space-y-2">
              <h2 className="text-sm font-semibold text-foreground">
                Status: {FACE_ENROLLMENT_STATE_LABEL[state]}
              </h2>
              <p className="text-sm text-foreground-secondary">{GUIDANCE[state]}</p>
              {state === "ENROLLMENT_AVAILABLE" ? (
                <p className="flex items-center gap-2 text-xs text-foreground-muted">
                  <Smartphone className="h-4 w-4" aria-hidden="true" />
                  Face capture needs your phone’s camera, so it is only available in the mobile app.
                </p>
              ) : null}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
