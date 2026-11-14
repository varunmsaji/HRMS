"use client";

import { useEffect, useRef, useState } from "react";

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
import { ApiError, describeApiError } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import type { InvitationCompose, InvitationPreview, OnboardingInvite } from "@/lib/onboarding/types";

interface InvitationComposerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** True when opened straight after the case was created; adds a "nothing sent yet" notice. */
  justCreated?: boolean;
  caseId: string;
  onSent: (result: OnboardingInvite) => void;
}

/** Choose template -> edit the full message (with a rendered preview tab) -> send. The preview is rendered by the server with the same code
 * that renders the real email, with an inert link (no token is created to preview). Sending
 * queues the email; it is NOT a delivery confirmation. */
export function InvitationComposer({ open, ...rest }: InvitationComposerProps) {
  // A fresh session (state, request id, send lock) is mounted for every open.
  return open ? <ComposerSession {...rest} /> : null;
}

function ComposerSession({
  onOpenChange,
  caseId,
  onSent,
  justCreated,
}: Omit<InvitationComposerProps, "open">) {
  const { user } = useAuth();
  const tz = user?.company_timezone ?? "Asia/Kolkata";
  const [compose, setCompose] = useState<InvitationCompose | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [templateKey, setTemplateKey] = useState("");
  const [step, setStep] = useState<"template" | "edit">("template");
  const [rendering, setRendering] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  // One id per compose session: if a send times out and is retried, the server recognises the
  // duplicate instead of issuing a second link. Re-created for each new session.
  const [requestId] = useState(() => crypto.randomUUID());
  const sendLockRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get<InvitationCompose>(`/onboarding-cases/${caseId}/invitation/compose`)
      .then((data) => {
        if (cancelled) return;
        setCompose(data);
        setSubject(data.default_subject);
        setBody(data.default_body);
        setTemplateKey(data.templates?.[0]?.key ?? "");
        if ((data.templates?.length ?? 0) <= 1) {
          void fillIn(data.default_subject, data.default_body, true);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setCompose(null);
        setLoadError(
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fillIn only uses stable setters and caseId
  }, [caseId, loadAttempt]);

  const templates = compose?.templates ?? [];

  /** Renders the template with this candidate's real details and shows the result as the text to
   * edit. Only `{{onboarding_url}}` stays a token: the real link is created when HR sends. */
  async function fillIn(subjectTemplate: string, bodyTemplate: string, fallback = false) {
    setRendering(true);
    setFieldError(null);
    try {
      const rendered = await apiClient.post<InvitationPreview>(
        `/onboarding-cases/${caseId}/invitation/preview`,
        { subject: subjectTemplate, body: bodyTemplate },
      );
      setSubject(rendered.subject);
      setBody(rendered.editable_body ?? bodyTemplate);
      setStep("edit");
    } catch (err) {
      if (fallback) {
        // No template choice to go back to: edit the raw template rather than strand HR.
        setSubject(subjectTemplate);
        setBody(bodyTemplate);
        setStep("edit");
      }
      setFieldError(
        err instanceof ApiError && err.status === 403
          ? "You don't have permission to preview this invitation."
          : describeApiError(err),
      );
    } finally {
      setRendering(false);
    }
  }

  function continueWithTemplate() {
    const chosen = templates.find((t) => t.key === templateKey);
    if (chosen) void fillIn(chosen.subject, chosen.body);
  }

  async function handleSend() {
    if (sendLockRef.current) return; // double-click guard, independent of React state timing
    sendLockRef.current = true;
    setSending(true);
    setSendError(null);
    try {
      const result = await apiClient.post<OnboardingInvite>(`/onboarding-cases/${caseId}/send-invite`, {
        subject,
        body,
        send_request_id: requestId,
      });
      onSent(result);
      onOpenChange(false);
    } catch (err) {
      sendLockRef.current = false;
      setSendError(
        err instanceof ApiError && err.status === 403
          ? "You don't have permission to send this invitation."
          : describeApiError(err),
      );
    } finally {
      setSending(false);
    }
  }

  const selecting = step === "template" && templates.length > 1;
  
  return (
    <Dialog open onOpenChange={(next) => (!sending ? onOpenChange(next) : null)}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{selecting ? "Choose a template" : "Review and send invitation"}</DialogTitle>
          <DialogDescription>
            {justCreated ? "The onboarding case has been created. No email has been sent yet. " : ""}
            {selecting
              ? "Pick the message to start from. You can edit it on the next step."
              : "Edit the message if you like. Nothing is sent until you click Send."}
          </DialogDescription>
        </DialogHeader>

        {loading || (rendering && !selecting) ? <p role="status">Loading…</p> : null}
        {loadError ? (
          <div className="space-y-2">
            <p role="alert" className="text-sm text-destructive">
              {loadError.status === 403
                ? "You don't have permission to send invitations."
                : `Could not load the invitation: ${describeApiError(loadError)}`}
            </p>
            {loadError.status !== 403 ? (
              <Button type="button" size="sm" variant="outline" onClick={() => {
                  setLoading(true);
                  setLoadError(null);
                  setLoadAttempt((n) => n + 1);
                }}>
                Retry
              </Button>
            ) : null}
          </div>
        ) : null}

        {compose && !loading && !(rendering && !selecting) ? (
          <div className="space-y-4">
            {!compose.invitable ? (
              <p role="alert" className="text-sm text-destructive">
                This case is no longer in a status an invitation can be sent for.
              </p>
            ) : null}

            {selecting && fieldError ? (
              <p role="alert" className="text-sm text-destructive">{fieldError}</p>
            ) : null}
            {selecting ? (
              <div role="radiogroup" aria-label="Template" className="space-y-2">
                {templates.map((t) => (
                  <label
                    key={t.key}
                    className={`flex cursor-pointer items-start gap-3 rounded-md border p-3 ${
                      t.key === templateKey ? "border-primary bg-primary/5" : "border-border"
                    }`}
                  >
                    <input
                      type="radio"
                      name="invitationTemplate"
                      className="mt-1"
                      checked={t.key === templateKey}
                      onChange={() => setTemplateKey(t.key)}
                    />
                    <span>
                      <span className="block text-sm font-medium">{t.name}</span>
                      <span className="block text-xs text-foreground-muted">{t.description}</span>
                    </span>
                  </label>
                ))}
              </div>
            ) : (
              <>
                <p className="text-sm">
                  <span className="text-foreground-muted">To: </span>
                  {compose.candidate_name} &lt;{compose.recipient_email}&gt;
                </p>

                {compose.has_active_link ? (
                  <p role="alert" className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
                    The candidate already has a live link
                    {compose.active_link_expires_at
                      ? ` (expires ${formatDateTime(compose.active_link_expires_at, tz)})`
                      : ""}
                    . Sending issues a <strong>new link and revokes the previous one</strong>.
                  </p>
                ) : null}

                <FormField id="invitationSubject" label="Subject" required>
                  <Input
                    value={subject}
                    maxLength={compose.subject_max_length}
                    onChange={(e) => setSubject(e.target.value)}
                  />
                </FormField>
                <div className="space-y-1.5">
                  <label htmlFor="invitationBody" className="text-sm font-medium">Message</label>
                  <div className="overflow-hidden rounded-md border border-border bg-surface focus-within:border-primary focus-within:ring-2 focus-within:ring-ring/20">
                    {/* The sent email opens with this logo above the greeting (added by the server). */}
                    <div className="border-b border-border bg-white px-3 py-2.5">
                      {/* eslint-disable-next-line @next/next/no-img-element -- mirrors the email's own <img> */}
                      <img
                        src="/brand/krewoxa-logo-email.png"
                        alt="Krewoxa"
                        width={120}
                        height={26}
                        className="h-[26px] w-auto"
                      />
                    </div>
                    <textarea
                      id="invitationBody"
                      value={body}
                      rows={18}
                      maxLength={compose.body_max_length}
                      onChange={(e) => setBody(e.target.value)}
                      className="block w-full resize-y border-0 bg-transparent px-3 py-2 text-sm text-foreground focus-visible:outline-none"
                    />
                  </div>
                  <p className="text-xs text-foreground-muted">
                    This is the email as the candidate will see it, with the Krewoxa logo above the
                    greeting. Keep {"{{onboarding_url}}"} where the secure link should go; it is replaced
                    with their personal link when you send.
                  </p>
                </div>
                {fieldError ? <p role="alert" className="text-sm text-destructive">{fieldError}</p> : null}
                {sendError ? <p role="alert" className="text-sm text-destructive">{sendError}</p> : null}
              </>
            )}
          </div>
        ) : null}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={sending}>
            Cancel
          </Button>
          {selecting ? (
            <Button type="button" onClick={continueWithTemplate} disabled={!compose?.invitable || !templateKey || rendering}>
              {rendering ? "Preparing…" : "Next"}
            </Button>
          ) : (
            <>
              {templates.length > 1 ? (
                <Button type="button" variant="outline" onClick={() => setStep("template")} disabled={sending}>
                  Back
                </Button>
              ) : null}
              <Button type="button" onClick={() => void handleSend()} disabled={sending || rendering || !compose?.invitable}>
                {sending ? "Queuing…" : "Send invitation"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
