"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { describeMessageStatus } from "@/lib/onboarding/invitation";
import type { OnboardingMessage } from "@/lib/onboarding/types";

interface InvitationHistoryProps {
  caseId: string;
  currentUserId?: string;
  /** Change to re-fetch (e.g. after a send). */
  refreshKey: number;
  canResend: boolean;
  onResend: () => void;
}

function when(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function InvitationHistory({ caseId, currentUserId, refreshKey, canResend, onResend }: InvitationHistoryProps) {
  const [messages, setMessages] = useState<OnboardingMessage[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get<OnboardingMessage[]>(`/onboarding-cases/${caseId}/messages`)
      .then((data) => {
        if (cancelled) return;
        setMessages(data);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setMessages(null);
        setError(
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        );
      });
    return () => {
      cancelled = true;
    };
  }, [caseId, refreshKey]);

  return (
    <section aria-label="Invitation emails" className="space-y-2">
      <h3 className="text-sm font-medium text-foreground">Invitation emails</h3>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error.status === 403
            ? "You don't have permission to view invitation history."
            : `Could not load invitation history: ${describeApiError(error)}`}
        </p>
      ) : messages === null ? (
        <p role="status" className="text-sm text-foreground-muted">Loading…</p>
      ) : messages.length === 0 ? (
        <p className="text-sm text-foreground-muted">No invitation has been sent yet.</p>
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {messages.map((m) => {
            const info = describeMessageStatus(m.status);
            return (
              <li key={m.id} className="space-y-1 px-3 py-2 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">{m.subject}</span>
                  <span data-testid="message-status" title={info.description}>{info.label}</span>
                </div>
                <p className="text-foreground-muted">
                  To {m.recipient_email} · by {m.created_by_user_id === currentUserId ? "you" : "another HR user"} ·{" "}
                  {when(m.created_at)}
                </p>
                <p className="text-foreground-muted">
                  {info.description}
                  {m.last_attempt_at ? ` Last attempt: ${when(m.last_attempt_at)}.` : ""}
                  {m.provider_accepted_at ? ` Accepted: ${when(m.provider_accepted_at)}.` : ""}
                </p>
                {info.needsResend && canResend ? (
                  <Button type="button" variant="outline" size="sm" onClick={onResend}>
                    Send new invitation
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
