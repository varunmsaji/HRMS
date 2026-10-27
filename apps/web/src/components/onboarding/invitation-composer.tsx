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
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { insertPlaceholder } from "@/lib/onboarding/invitation";
import type { InvitationCompose, InvitationPreview, OnboardingInvite } from "@/lib/onboarding/types";

interface InvitationComposerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  caseId: string;
  onSent: (result: OnboardingInvite) => void;
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

/** Compose -> Preview -> Confirm send. The preview is rendered by the server with the same code
 * that renders the real email, with an inert link (no token is created to preview). Sending
 * queues the email; it is NOT a delivery confirmation. */
export function InvitationComposer({ open, ...rest }: InvitationComposerProps) {
  // A fresh session (state, request id, send lock) is mounted for every open.
  return open ? <ComposerSession {...rest} /> : null;
}

function ComposerSession({ onOpenChange, caseId, onSent }: Omit<InvitationComposerProps, "open">) {
  const [compose, setCompose] = useState<InvitationCompose | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
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
  }, [caseId]);

  function handleInsert(key: string) {
    const el = bodyRef.current;
    const next = insertPlaceholder(body, el?.selectionStart ?? body.length, el?.selectionEnd ?? body.length, key);
    setBody(next.value);
    setPreview(null);
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(next.caret, next.caret);
    });
  }

  async function handlePreview() {
    setPreviewing(true);
    setFieldError(null);
    try {
      setPreview(
        await apiClient.post<InvitationPreview>(`/onboarding-cases/${caseId}/invitation/preview`, {
          subject,
          body,
        }),
      );
    } catch (err) {
      setPreview(null);
      setFieldError(
        err instanceof ApiError && err.status === 403
          ? "You don't have permission to preview this invitation."
          : describeApiError(err),
      );
    } finally {
      setPreviewing(false);
    }
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

  const required = compose?.placeholders.filter((p) => p.key !== "onboarding_url") ?? [];

  return (
    <Dialog open onOpenChange={(next) => (!sending ? onOpenChange(next) : null)}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{preview ? "Review and send invitation" : "Compose invitation"}</DialogTitle>
          <DialogDescription>
            A pre-joining onboarding invitation — not an offer letter. Nothing is sent until you confirm.
          </DialogDescription>
        </DialogHeader>

        {loading ? <p role="status">Loading…</p> : null}
        {loadError ? (
          <p role="alert" className="text-sm text-destructive">
            {loadError.status === 403
              ? "You don't have permission to send invitations."
              : `Could not load the invitation: ${describeApiError(loadError)}`}
          </p>
        ) : null}

        {compose && !loading ? (
          <div className="space-y-4">
            <dl className="grid grid-cols-1 gap-x-4 gap-y-1 rounded-md border border-border bg-background-secondary p-3 text-sm sm:grid-cols-2">
              <div><dt className="inline text-foreground-muted">To: </dt><dd className="inline">{compose.candidate_name} &lt;{compose.recipient_email}&gt;</dd></div>
              <div><dt className="inline text-foreground-muted">Company: </dt><dd className="inline">{compose.company_name}</dd></div>
              <div><dt className="inline text-foreground-muted">Designation: </dt><dd className="inline">{compose.designation ?? "—"}</dd></div>
              <div><dt className="inline text-foreground-muted">Department: </dt><dd className="inline">{compose.department ?? "—"}</dd></div>
              <div><dt className="inline text-foreground-muted">Joining date: </dt><dd className="inline">{compose.proposed_joining_date}</dd></div>
              <div><dt className="inline text-foreground-muted">New link valid for: </dt><dd className="inline">{compose.link_valid_days} days</dd></div>
            </dl>

            {!compose.invitable ? (
              <p role="alert" className="text-sm text-destructive">
                This case is no longer in a status an invitation can be sent for.
              </p>
            ) : null}

            {compose.has_active_link ? (
              <p role="alert" className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
                The candidate already has a live link
                {compose.active_link_expires_at ? ` (expires ${formatDate(compose.active_link_expires_at)})` : ""}.
                Sending issues a <strong>new link and revokes the previous one</strong>.
              </p>
            ) : null}

            {preview ? (
              <div className="space-y-3" data-testid="invitation-preview">
                <p className="text-sm">
                  <span className="text-foreground-muted">Subject: </span>
                  <strong>{preview.subject}</strong>
                </p>
                <iframe
                  title="Email preview"
                  sandbox=""
                  srcDoc={`<body style="font-family:sans-serif;font-size:14px">${preview.html_body}</body>`}
                  className="h-72 w-full rounded-md border border-border bg-white"
                />
                <p className="text-xs text-foreground-muted">
                  The link shown is a non-functional placeholder; the real secure link is created when you send.
                </p>
                {sendError ? (
                  <p role="alert" className="text-sm text-destructive">{sendError}</p>
                ) : null}
              </div>
            ) : (
              <>
                <FormField id="invitationSubject" label="Subject" required>
                  <Input
                    value={subject}
                    maxLength={compose.subject_max_length}
                    onChange={(e) => { setSubject(e.target.value); setPreview(null); }}
                  />
                </FormField>
                <div className="space-y-1.5">
                  <label htmlFor="invitationBody" className="text-sm font-medium">Message</label>
                  <textarea
                    id="invitationBody"
                    ref={bodyRef}
                    value={body}
                    rows={12}
                    maxLength={compose.body_max_length}
                    onChange={(e) => { setBody(e.target.value); setPreview(null); }}
                    className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  />
                  <div className="flex items-center gap-2">
                    <label htmlFor="invitationPlaceholder" className="text-sm text-foreground-muted">Insert field</label>
                    <NativeSelect
                      id="invitationPlaceholder"
                      className="w-64"
                      value=""
                      onChange={(e) => { if (e.target.value) handleInsert(e.target.value); }}
                    >
                      <option value="">Choose…</option>
                      {compose.placeholders.map((p) => (
                        <option key={p.key} value={p.key}>{p.label}</option>
                      ))}
                    </NativeSelect>
                  </div>
                  <p className="text-xs text-foreground-muted">
                    The message must include the secure link. Lines using a field the candidate does not have
                    ({required.filter((p) => !p.required).map((p) => p.label.toLowerCase()).join(", ")}) are left out.
                  </p>
                </div>
                {fieldError ? <p role="alert" className="text-sm text-destructive">{fieldError}</p> : null}
              </>
            )}
          </div>
        ) : null}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={sending}>
            Cancel
          </Button>
          {preview ? (
            <>
              <Button type="button" variant="outline" onClick={() => setPreview(null)} disabled={sending}>
                Edit
              </Button>
              <Button type="button" onClick={() => void handleSend()} disabled={sending || !compose?.invitable}>
                {sending ? "Queuing…" : "Confirm & send"}
              </Button>
            </>
          ) : (
            <Button
              type="button"
              onClick={() => void handlePreview()}
              disabled={!compose || previewing || !compose.invitable}
            >
              {previewing ? "Rendering…" : "Preview"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
