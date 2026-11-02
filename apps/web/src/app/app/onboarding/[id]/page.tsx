"use client";

import { FACE_ENROLLMENT_STATE_LABEL } from "@/lib/attendance/types";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { BackButton } from "@/components/common/back-button";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import {
  CancelOnboardingDialog,
  ONBOARDING_CANCELLABLE_STATUSES,
} from "@/components/onboarding/cancel-onboarding-dialog";
import { DocumentRejectDialog } from "@/components/onboarding/document-review-dialog";
import { InvitationComposer } from "@/components/onboarding/invitation-composer";
import { InvitationHistory } from "@/components/onboarding/invitation-history";
import { OnboardingStatusBadge } from "@/components/onboarding/onboarding-status-badge";
import { SectionRejectDialog } from "@/components/onboarding/section-review-dialog";
import { Badge } from "@/components/ui/badge";
import { HorizontalScroll } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import { formatDateTime } from "@/lib/attendance/format";
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import type { LegalEntity } from "@/lib/legal-entity/types";
import {
  ONBOARDING_CASE_INVITABLE_STATUSES,
  ONBOARDING_DOCUMENT_TYPE_LABELS,
  ONBOARDING_SECTION_LABELS,
  ONBOARDING_SECTION_NAMES,
  type OnboardingCaseDetail,
  type OnboardingDocumentWithUrl,
  type OnboardingInvite,
  type OnboardingSectionName,
} from "@/lib/onboarding/types";

function ReviewStatusBadge({ status }: { status: string }) {
  if (status === "VERIFIED") return <Badge variant="success">Verified</Badge>;
  if (status === "REJECTED") return <Badge variant="danger">Rejected</Badge>;
  return <Badge variant="outline">Pending</Badge>;
}

function LinkStatus({
  status,
  expiresAt,
  tz,
}: {
  status: OnboardingCaseDetail["token_status"];
  expiresAt: string | null;
  tz: string;
}) {
  if (!status) return null;
  if (status === "ACTIVE") {
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant="success">Link active</Badge>
        <span className="text-foreground-muted">
          {expiresAt ? `Expires ${formatDateTime(expiresAt, tz)}` : null}
        </span>
      </div>
    );
  }
  if (status === "EXPIRED") {
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant="danger">Link expired</Badge>
        <span className="text-foreground-muted">
          {expiresAt ? `Expired ${formatDateTime(expiresAt, tz)} — ` : ""}Resend the invite to
          generate a new one.
        </span>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <Badge variant="outline">Link revoked</Badge>
      <span className="text-foreground-muted">A newer link has since been issued.</span>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fieldLabel(key: string): string {
  return key
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function FlatFields({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data).filter(([, value]) => value !== null && value !== "");
  if (entries.length === 0) {
    return <p className="text-sm text-foreground-muted">Not filled in yet.</p>;
  }
  return (
    <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
            {fieldLabel(key)}
          </dt>
          <dd className="mt-0.5 text-foreground">
            {typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Most sections are a single flat object (`personal_info`, `bank_info`, ...); a few
 * (`previous_employment_info`, and any future list-shaped section) are `{items: [...]}` — a
 * candidate may have several past employers, all concurrently valid. Dispatches to a per-item
 * card list for those, since flattening an array through `String(value)` would otherwise render
 * as unreadable `"[object Object],[object Object]"`. */
function SectionFields({ data }: { data: Record<string, unknown> }) {
  if (Array.isArray(data.items)) {
    const items = data.items as Record<string, unknown>[];
    if (items.length === 0) {
      return <p className="text-sm text-foreground-muted">None added.</p>;
    }
    return (
      <div className="space-y-3">
        {items.map((item, index) => (
          <div key={index} className="rounded-md border border-border p-3">
            <FlatFields data={item} />
          </div>
        ))}
      </div>
    );
  }
  return <FlatFields data={data} />;
}

interface ReferenceData {
  branches: Branch[];
  departments: Department[];
  designations: Designation[];
  legalEntities: LegalEntity[];
}

function DetailField({ label, value }: { label: string; value: string | null | undefined }) {
  const display = value && value.trim() ? value : "Not set";
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</dt>
      <dd className={`mt-0.5 break-words text-sm ${value && value.trim() ? "text-foreground" : "text-foreground-muted"}`}>
        {display}
      </dd>
    </div>
  );
}

function nameIn<T extends { id: string; name?: string; title?: string }>(
  list: T[] | undefined,
  id: string | null,
): string {
  if (!id) return "";
  const item = list?.find((entry) => entry.id === id);
  return item?.name ?? item?.title ?? "Unknown";
}

const REVIEWABLE_CASE_STATUSES = ["SUBMITTED", "UNDER_REVIEW"];

export default function OnboardingCaseDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const { can } = usePermissions();
  const datePattern = useCompanyDatePattern();
  const { user } = useAuth();

  const [onboardingCase, setOnboardingCase] = useState<OnboardingCaseDetail | null>(null);
  const [refs, setRefs] = useState<ReferenceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [composerOpen, setComposerOpen] = useState(false);
  const [composerJustCreated, setComposerJustCreated] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const autoOpenHandledRef = useRef(false);
  const canRef = useRef(can);
  useEffect(() => {
    canRef.current = can;
  }, [can]);
  const [historyKey, setHistoryKey] = useState(0);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [reviewingSection, setReviewingSection] = useState<OnboardingSectionName | null>(null);
  const [verifyingAll, setVerifyingAll] = useState(false);
  const [sendingLoginLink, setSendingLoginLink] = useState(false);
  const [loginLinkUrl, setLoginLinkUrl] = useState<string | null>(null);
  const [rejectSection, setRejectSection] = useState<OnboardingSectionName | null>(null);
  const [requestingChanges, setRequestingChanges] = useState(false);
  const [activating, setActivating] = useState(false);

  const [documents, setDocuments] = useState<OnboardingDocumentWithUrl[] | null>(null);
  const [documentsError, setDocumentsError] = useState(false);
  const [reviewingDocumentId, setReviewingDocumentId] = useState<string | null>(null);
  const [rejectDocument, setRejectDocument] = useState<OnboardingDocumentWithUrl | null>(null);

  const loadDocuments = useCallback(async () => {
    try {
      const data = await apiClient.get<OnboardingDocumentWithUrl[]>(
        `/onboarding-cases/${params.id}/documents`,
      );
      setDocuments(data);
      setDocumentsError(false);
    } catch {
      setDocuments(null);
      setDocumentsError(true);
    }
  }, [params.id]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, branches, departments, designations, legalEntities] = await Promise.all([
        apiClient.get<OnboardingCaseDetail>(`/onboarding-cases/${params.id}`),
        apiClient.get<Branch[]>("/branches").catch(() => []),
        apiClient.get<Department[]>("/departments").catch(() => []),
        apiClient.get<Designation[]>("/designations").catch(() => []),
        apiClient.get<LegalEntity[]>("/legal-entities").catch(() => []),
      ]);
      setOnboardingCase(data);
      setRefs({ branches, departments, designations, legalEntities });
      // The create flow lands here with `?compose=1`: open the composer once (never sends
      // anything), then drop the param so a refresh or back-navigation doesn't reopen it.
      if (!autoOpenHandledRef.current) {
        const url = new URL(window.location.href);
        if (url.searchParams.get("compose") === "1") {
          autoOpenHandledRef.current = true;
          url.searchParams.delete("compose");
          window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
          if (
            canRef.current("ONBOARDING.CREATE") &&
            ONBOARDING_CASE_INVITABLE_STATUSES.includes(data.status)
          ) {
            setComposerJustCreated(true);
            setComposerOpen(true);
          }
        }
      }
    } catch (err) {
      setOnboardingCase(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void load();
    void loadDocuments();
  }, [load, loadDocuments]);

  async function handleVerifyDocument(document: OnboardingDocumentWithUrl) {
    setReviewingDocumentId(document.id);
    try {
      const updated = await apiClient.post<OnboardingDocumentWithUrl>(
        `/onboarding-cases/${params.id}/documents/${document.id}/review`,
        { status: "VERIFIED" },
      );
      setDocuments((prev) =>
        (prev ?? []).map((d) => (d.id === document.id ? { ...updated, download_url: d.download_url } : d)),
      );
      toast({ title: "Document verified", variant: "success" });
      void load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        toast({ title: "You don't have permission to review this document", variant: "danger" });
        return;
      }
      toast({ title: "Could not verify document", description: describeApiError(err), variant: "danger" });
    } finally {
      setReviewingDocumentId(null);
    }
  }

  async function handleVerifySection(section: OnboardingSectionName) {
    setReviewingSection(section);
    try {
      await apiClient.post(`/onboarding-cases/${params.id}/sections/${section}/review`, {
        status: "VERIFIED",
      });
      toast({ title: "Section verified", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        toast({ title: "You don't have permission to review this section", variant: "danger" });
        return;
      }
      toast({ title: "Could not verify section", description: describeApiError(err), variant: "danger" });
    } finally {
      setReviewingSection(null);
    }
  }

  /** Verifies every section and document still `PENDING` in one go (rejected items are left
   * alone — HR rejected those on purpose). Runs the existing per-item review calls in order; the
   * API moves the case to `VERIFIED` itself when the last one lands. */
  async function handleVerifyAll() {
    if (!onboardingCase) return;
    setVerifyingAll(true);
    try {
      const pendingSections = ONBOARDING_SECTION_NAMES.filter((section) => {
        const status = onboardingCase.section_reviews.find((r) => r.section === section)?.status;
        return status !== "VERIFIED" && status !== "REJECTED";
      });
      const pendingDocuments = (documents ?? []).filter((d) => d.status === "PENDING");
      for (const section of pendingSections) {
        await apiClient.post(`/onboarding-cases/${params.id}/sections/${section}/review`, {
          status: "VERIFIED",
        });
      }
      for (const document of pendingDocuments) {
        await apiClient.post(`/onboarding-cases/${params.id}/documents/${document.id}/review`, {
          status: "VERIFIED",
        });
      }
      toast({ title: "Everything verified", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        toast({ title: "You don't have permission to review this case", variant: "danger" });
      } else {
        toast({ title: "Could not verify everything", description: describeApiError(err), variant: "danger" });
      }
    } finally {
      setVerifyingAll(false);
      void load();
      void loadDocuments();
    }
  }

  async function handleRequestChanges() {
    setRequestingChanges(true);
    try {
      const updated = await apiClient.post<OnboardingCaseDetail>(
        `/onboarding-cases/${params.id}/request-changes`,
      );
      setOnboardingCase((prev) => (prev ? { ...prev, status: updated.status, version: updated.version } : prev));
      toast({ title: "Changes requested", description: "The candidate has been notified.", variant: "success" });
      void load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast({ title: "Nothing to request changes for", description: describeApiError(err), variant: "danger" });
        return;
      }
      toast({ title: "Could not request changes", description: describeApiError(err), variant: "danger" });
    } finally {
      setRequestingChanges(false);
    }
  }

  async function handleActivate() {
    setActivating(true);
    try {
      const updated = await apiClient.post<OnboardingCaseDetail>(
        `/onboarding-cases/${params.id}/activate`,
      );
      toast({
        title: "Employee activated",
        description: `Employee record created (id ${updated.employee_id}).`,
        variant: "success",
      });
      void load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        toast({ title: "You don't have permission to activate this case", variant: "danger" });
        return;
      }
      toast({ title: "Could not activate", description: describeApiError(err), variant: "danger" });
    } finally {
      setActivating(false);
    }
  }

  function handleInviteQueued(result: OnboardingInvite) {
    setInviteUrl(result.invite_url);
    setHistoryKey((k) => k + 1);
    // "Queued" is all the API can say at this point - never "sent"/"delivered".
    toast({
      title: result.email_queued ? "Invitation queued" : "Invitation link created, email not queued",
      description: result.email_queued
        ? `The email to ${result.case.personal_email} is queued for delivery. Track its status below.`
        : "The link is ready to copy, but no email was queued. Send a new invitation to retry.",
      variant: result.email_queued ? "success" : "danger",
    });
    void load();
  }

  /** Employee login setup: `POST /employees/{id}/invite` emails a one-time link where the new
   * employee chooses a password, then signs in with their email + that password. Shown here too
   * (not only emailed) because email delivery isn't configured in every environment. */
  async function handleSendLoginLink() {
    if (!onboardingCase?.employee_id) return;
    setSendingLoginLink(true);
    try {
      const result = await apiClient.post<{ invite_url: string; email: string; email_sent: boolean }>(
        `/employees/${onboardingCase.employee_id}/invite`,
      );
      setLoginLinkUrl(result.invite_url);
      toast({
        title: result.email_sent ? `Login link sent to ${result.email}` : "Login link created",
        description: result.email_sent
          ? "They can set a password from the email and sign in."
          : "The link is ready to copy — email delivery isn't configured in this environment.",
        variant: "success",
      });
    } catch (err) {
      toast({ title: "Could not send login link", description: describeApiError(err), variant: "danger" });
    } finally {
      setSendingLoginLink(false);
    }
  }

  async function handleCopyLoginLink() {
    if (!loginLinkUrl) return;
    try {
      await navigator.clipboard.writeText(loginLinkUrl);
      toast({ title: "Link copied", variant: "success" });
    } catch {
      toast({ title: "Could not copy link", variant: "danger" });
    }
  }

  async function handleCopyLink() {
    if (!inviteUrl) return;
    try {
      await navigator.clipboard.writeText(inviteUrl);
      toast({ title: "Link copied", variant: "success" });
    } catch {
      toast({ title: "Could not copy link", variant: "danger" });
    }
  }

  if (loading) {
    return <LoadingState label="Loading onboarding case…" />;
  }

  if (error || !onboardingCase) {
    return (
      <ErrorState
        message={
          error?.status === 404
            ? "This onboarding case could not be found."
            : error?.status === 403
              ? "You do not have permission to view this onboarding case."
              : error?.message ?? "Something went wrong."
        }
        onRetry={() => void load()}
      />
    );
  }

  const candidateName = [onboardingCase.candidate_first_name, onboardingCase.candidate_last_name]
    .filter(Boolean)
    .join(" ");
  const canInvite = can("ONBOARDING.CREATE");
  const canReview = can("ONBOARDING.REVIEW");
  const canActivate = can("ONBOARDING.ACTIVATE");
  const canCancel =
    can("ONBOARDING.CANCEL") && ONBOARDING_CANCELLABLE_STATUSES.includes(onboardingCase.status);
  const isInvitable = ONBOARDING_CASE_INVITABLE_STATUSES.includes(onboardingCase.status);
  const isReviewable = REVIEWABLE_CASE_STATUSES.includes(onboardingCase.status);
  const inviteLabel =
    onboardingCase.status === "DRAFT"
      ? "Compose Invitation"
      : onboardingCase.status === "ACTIVATED"
        ? "Get New Link"
        : "Resend Invitation";
  const hasUnverified =
    ONBOARDING_SECTION_NAMES.some((section) => {
      const status = onboardingCase.section_reviews.find((r) => r.section === section)?.status;
      return status !== "VERIFIED" && status !== "REJECTED";
    }) || (documents ?? []).some((d) => d.status === "PENDING");
  const hasAnyRejection =
    onboardingCase.section_reviews.some((r) => r.status === "REJECTED") ||
    (documents ?? []).some((d) => d.status === "REJECTED");

  return (
    <div className="space-y-6">
      <PageHeader
        title={candidateName || "Onboarding case"}
        description="HR-started onboarding case — review each section, then activate once everything is verified."
        actions={
          <BackButton href="/app/onboarding">Back to onboarding</BackButton>
        }
      />

      {canInvite ? (
        <InvitationComposer
          open={composerOpen}
          onOpenChange={(next) => {
            setComposerOpen(next);
            if (!next) setComposerJustCreated(false);
          }}
          justCreated={composerJustCreated}
          caseId={params.id}
          onSent={handleInviteQueued}
        />
      ) : null}

      {canCancel ? (
        <CancelOnboardingDialog
          open={cancelOpen}
          onOpenChange={setCancelOpen}
          caseId={params.id}
          candidateName={candidateName}
          hasLiveLink={onboardingCase.token_status === "ACTIVE"}
          onCancelled={() => {
            void load();
            setHistoryKey((k) => k + 1);
          }}
        />
      ) : null}

      <Card>
        <CardContent className="space-y-6 pt-6">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-foreground">Status</h3>
            <div className="flex items-center gap-3">
              <OnboardingStatusBadge status={onboardingCase.status} />
              {canInvite && isInvitable ? (
                <Button type="button" size="sm" onClick={() => setComposerOpen(true)}>
                  {inviteLabel}
                </Button>
              ) : null}
              {canReview && isReviewable && hasUnverified ? (
                <Button type="button" size="sm" onClick={() => void handleVerifyAll()} disabled={verifyingAll}>
                  {verifyingAll ? "Verifying…" : "Verify All"}
                </Button>
              ) : null}
              {canReview && onboardingCase.status === "UNDER_REVIEW" && hasAnyRejection ? (
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  onClick={() => void handleRequestChanges()}
                  disabled={requestingChanges}
                >
                  {requestingChanges ? "Requesting…" : "Request Changes"}
                </Button>
              ) : null}
              {canCancel ? (
                <Button type="button" size="sm" variant="outline" onClick={() => setCancelOpen(true)}>
                  Cancel Onboarding
                </Button>
              ) : null}
              {canActivate && onboardingCase.status === "VERIFIED" ? (
                <Button type="button" size="sm" onClick={() => void handleActivate()} disabled={activating}>
                  {activating ? "Activating…" : "Activate"}
                </Button>
              ) : null}
              {onboardingCase.status === "ACTIVATED" && onboardingCase.employee_id && can("EMPLOYEE.INVITE") ? (
                <Button type="button" size="sm" onClick={() => void handleSendLoginLink()} disabled={sendingLoginLink}>
                  {sendingLoginLink ? "Sending…" : "Send Login Link"}
                </Button>
              ) : null}
              {onboardingCase.status === "ACTIVATED" && onboardingCase.employee_id ? (
                <Link
                  href={`/app/employees/${onboardingCase.employee_id}`}
                  className="text-sm text-foreground-secondary hover:underline"
                >
                  View employee record →
                </Link>
              ) : null}
            </div>
          </div>

          {inviteUrl ? (
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-background-secondary px-3 py-2 text-sm">
              <span className="text-foreground-muted">Invite link:</span>
              <a
                href={inviteUrl}
                target="_blank"
                rel="noreferrer"
                className="truncate text-foreground underline"
              >
                {inviteUrl}
              </a>
              <Button type="button" variant="outline" size="sm" onClick={() => void handleCopyLink()}>
                Copy link
              </Button>
            </div>
          ) : null}

          {loginLinkUrl ? (
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-background-secondary px-3 py-2 text-sm">
              <span className="text-foreground-muted">Login setup link:</span>
              <a href={loginLinkUrl} target="_blank" rel="noreferrer" className="truncate text-foreground underline">
                {loginLinkUrl}
              </a>
              <Button type="button" variant="outline" size="sm" onClick={() => void handleCopyLoginLink()}>
                Copy link
              </Button>
            </div>
          ) : null}

          {canInvite || can("ONBOARDING.VIEW") ? (
            <InvitationHistory
              caseId={onboardingCase.id}
              currentUserId={user?.id}
              refreshKey={historyKey}
              canResend={canInvite && isInvitable}
              onResend={() => setComposerOpen(true)}
            />
          ) : null}

          <LinkStatus
            status={onboardingCase.token_status}
            expiresAt={onboardingCase.token_expires_at}
            tz={user?.company_timezone ?? "Asia/Kolkata"}
          />

          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <DetailField label="Candidate first name" value={onboardingCase.candidate_first_name} />
            <DetailField label="Candidate last name" value={onboardingCase.candidate_last_name} />
            <DetailField label="Personal email" value={onboardingCase.personal_email} />
            <DetailField label="Personal mobile" value={onboardingCase.personal_mobile} />
            <DetailField
              label="Proposed joining date"
              value={formatCompanyDate(onboardingCase.proposed_joining_date, datePattern)}
            />
            <DetailField label="Company" value={nameIn(refs?.legalEntities, onboardingCase.legal_entity_id)} />
            <DetailField label="Branch" value={nameIn(refs?.branches, onboardingCase.branch_id)} />
            <DetailField label="Department" value={nameIn(refs?.departments, onboardingCase.department_id)} />
            <DetailField label="Designation" value={nameIn(refs?.designations, onboardingCase.designation_id)} />
          </dl>
        </CardContent>
      </Card>

      {ONBOARDING_SECTION_NAMES.map((section) => {
        const review = onboardingCase.section_reviews.find((r) => r.section === section);
        const status = review?.status ?? "PENDING";
        return (
          <Card key={section}>
            <CardContent className="space-y-4 pt-6">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-foreground">{ONBOARDING_SECTION_LABELS[section]}</h3>
                <div className="flex items-center gap-3">
                  <ReviewStatusBadge status={status} />
                  {canReview && isReviewable && status !== "VERIFIED" ? (
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={reviewingSection === section}
                        onClick={() => void handleVerifySection(section)}
                      >
                        Verify
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={reviewingSection === section}
                        onClick={() => setRejectSection(section)}
                      >
                        Reject
                      </Button>
                    </div>
                  ) : null}
                </div>
              </div>
              {status === "REJECTED" && review?.rejection_reason ? (
                <p className="text-sm text-danger">Rejected: {review.rejection_reason}</p>
              ) : null}
              <SectionFields data={onboardingCase[section]} />
            </CardContent>
          </Card>
        );
      })}

      {onboardingCase.face_enrollment_required ? (
        <Card>
          <CardContent className="space-y-2 pt-6">
            <h3 className="text-sm font-medium text-foreground">Face enrollment</h3>
            <p className="text-sm text-foreground-muted">
              Your company requires face enrollment as part of onboarding.
            </p>
            {onboardingCase.face_enrollment ? (
              <p className="text-sm text-foreground">
                Status: {FACE_ENROLLMENT_STATE_LABEL[onboardingCase.face_enrollment.state]}
                {onboardingCase.face_enrollment.requirement_met
                  ? " — requirement met"
                  : " — onboarding is not complete until HR approves the enrollment"}
              </p>
            ) : (
              <p className="text-sm text-foreground-muted">
                Available after the employee is activated.
              </p>
            )}
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardContent className="space-y-4 pt-6">
          <h3 className="text-sm font-medium text-foreground">Documents</h3>

          {documentsError ? (
            <p className="text-sm text-foreground-muted">
              You do not have permission to view documents, or none have been uploaded yet.
            </p>
          ) : null}

          {!documentsError && documents && documents.length === 0 ? (
            <p className="text-sm text-foreground-muted">No documents uploaded yet.</p>
          ) : null}

          {!documentsError && documents && documents.length > 0 ? (
            <HorizontalScroll>
              <table className="w-full min-w-[560px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wide text-foreground-muted">
                    <th className="py-2 pr-4">Type</th>
                    <th className="py-2 pr-4">File</th>
                    <th className="py-2 pr-4">Size</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-0">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {documents.map((document) => (
                    <tr key={document.id} className="border-b border-border last:border-0">
                      <td className="py-3 pr-4 text-foreground-secondary">
                        {ONBOARDING_DOCUMENT_TYPE_LABELS[
                          document.document_type as keyof typeof ONBOARDING_DOCUMENT_TYPE_LABELS
                        ] ?? document.document_type}
                      </td>
                      <td className="py-3 pr-4">
                        <a
                          href={document.download_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-foreground underline"
                        >
                          {document.original_filename}
                        </a>
                      </td>
                      <td className="py-3 pr-4 text-foreground-secondary">{formatBytes(document.size_bytes)}</td>
                      <td className="py-3 pr-4">
                        <ReviewStatusBadge status={document.status} />
                        {document.status === "REJECTED" && document.rejection_reason ? (
                          <p className="mt-1 text-xs text-foreground-muted">{document.rejection_reason}</p>
                        ) : null}
                      </td>
                      <td className="py-3 pr-0">
                        {canReview ? (
                          <div className="flex gap-2">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={reviewingDocumentId === document.id}
                              onClick={() => void handleVerifyDocument(document)}
                            >
                              Verify
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={reviewingDocumentId === document.id}
                              onClick={() => setRejectDocument(document)}
                            >
                              Reject
                            </Button>
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </HorizontalScroll>
          ) : null}
        </CardContent>
      </Card>

      <DocumentRejectDialog
        open={rejectDocument !== null}
        onOpenChange={(open) => (!open ? setRejectDocument(null) : null)}
        caseId={params.id}
        document={rejectDocument}
        onDone={(updated) => {
          setDocuments((prev) => (prev ?? []).map((d) => (d.id === updated.id ? updated : d)));
          setRejectDocument(null);
          void load();
        }}
      />

      <SectionRejectDialog
        open={rejectSection !== null}
        onOpenChange={(open) => (!open ? setRejectSection(null) : null)}
        caseId={params.id}
        section={rejectSection}
        onDone={(updatedCase) => {
          setOnboardingCase(updatedCase);
          setRejectSection(null);
        }}
      />
    </div>
  );
}
