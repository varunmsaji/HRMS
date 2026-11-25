"use client";

import { Mail } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import { DIGEST_SETTINGS_PATH, type DigestSettings } from "@/lib/attendance/digest-settings";

/** Which attendance emails this company receives. Both are on by default; this page opts out. The
 * API decides who may change it (`ATTENDANCE.POLICY_MANAGE`): a caller without it sees the
 * refusal, not an editable form. */
export default function AttendanceDigestsPage() {
  const [saved, setSaved] = useState<DigestSettings | null>(null);
  const [manager, setManager] = useState(true);
  const [hr, setHr] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get<DigestSettings>(DIGEST_SETTINGS_PATH)
      .then((data) => {
        if (cancelled) return;
        setSaved(data);
        setManager(data.manager_daily_enabled);
        setHr(data.hr_weekly_enabled);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(describeApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = useCallback(() => {
    setError(null);
    setAttempt((n) => n + 1);
  }, []);

  async function save() {
    setBusy(true);
    setSaveError(null);
    setNotice(null);
    try {
      const data = await apiClient.put<DigestSettings>(DIGEST_SETTINGS_PATH, {
        manager_daily_enabled: manager,
        hr_weekly_enabled: hr,
      });
      setSaved(data);
      setNotice("Saved.");
    } catch (err) {
      setSaveError(describeApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const dirty = saved !== null && (saved.manager_daily_enabled !== manager || saved.hr_weekly_enabled !== hr);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Attendance emails"
        description="Which attendance summaries your company receives by email. Both are on unless you switch them off here."
      />
      {error ? (
        <ErrorState message={error} onRetry={retry} />
      ) : saved === null ? (
        <LoadingState />
      ) : (
        <Card>
          <CardContent className="space-y-5 p-5">
            {!saved.deployment_enabled ? (
              <p role="status" className="rounded-md border border-warning-border bg-warning-subtle px-3 py-2 text-sm text-foreground">
                Attendance emails are switched off for this whole deployment, so nothing is sent yet. Your choices are saved
                and apply once they are switched on.
              </p>
            ) : null}
            <div className="flex items-start gap-3">
              <Checkbox id="digest-manager" checked={manager} onChange={(e) => setManager(e.target.checked)} className="mt-1" />
              <div>
                <label htmlFor="digest-manager" className="text-sm font-medium text-foreground">
                  Daily team note to managers
                </label>
                <p className="text-sm text-foreground-secondary">
                  On weekday mornings, each manager gets a note about their direct reports: who is absent, not checked in, late
                  or missing a punch, and requests waiting. Nothing is sent when there is nothing to say.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Checkbox id="digest-hr" checked={hr} onChange={(e) => setHr(e.target.checked)} className="mt-1" />
              <div>
                <label htmlFor="digest-hr" className="text-sm font-medium text-foreground">
                  Weekly summary to HR
                </label>
                <p className="text-sm text-foreground-secondary">
                  On Monday, last week&apos;s attendance against the week before, with patterns worth a look, to people who see
                  the whole company.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" onClick={save} disabled={busy || !dirty}>
                <Mail className="mr-1.5 h-4 w-4" aria-hidden="true" />
                {busy ? "Saving…" : "Save"}
              </Button>
              {notice ? (
                <span role="status" className="text-sm text-success">
                  {notice}
                </span>
              ) : null}
              {saveError ? (
                <span role="alert" className="text-sm text-danger">
                  {saveError}
                </span>
              ) : null}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
