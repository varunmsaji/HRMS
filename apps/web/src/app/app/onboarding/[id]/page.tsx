"use client";

import { FACE_ENROLLMENT_STATE_LABEL } from "@/lib/attendance/types";
import {
  BadgeCheck,
  Briefcase,
  Building2,
  Calendar,
  ChevronDown,
  CircleAlert,
  CircleCheck,
  Clock,
  Copy,
  ExternalLink,
  FileText,
  GitBranch,
  GraduationCap,
  Landmark,
  Layers,
  Mail,
  MapPin,
  Phone,
  ScanFace,
  ScrollText,
  User,
  Users,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { Collapse } from "@/components/common/collapse";
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
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
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
  if (status === "VERIFIED") return <Badge variant="success" dot>Verified</Badge>;
  if (status === "REJECTED") return <Badge variant="danger" dot>Rejected</Badge>;
  return <Badge variant="outline" dot>Pending</Badge>;
}

const SECTION_ICONS: Record<OnboardingSectionName, LucideIcon> = {
  personal_info: User,
  address_info: MapPin,
  emergency_contact: Phone,
  bank_info: Landmark,
  statutory_info: ScrollText,
  previous_employment_info: Briefcase,
  education_info: GraduationCap,
  nominee_info: Users,
};

/** Tinted icon tile whose colour follows the review status, so a scan down the page shows
 * what's done (green), what was sent back (red) and what still needs a look (neutral). */
function StatusIcon({ icon: Icon, status }: { icon: LucideIcon; status: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-md border",
        status === "VERIFIED"
          ? "border-success-border bg-success-subtle text-success"
          : status === "REJECTED"
            ? "border-danger-border bg-danger-subtle text-danger"
            : "border-border bg-muted text-foreground-secondary",
      )}
    >
      <Icon className="h-4 w-4" />
    </span>
  );
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
  if (!status) {
    return <p className="text-sm text-foreground-muted">No onboarding link has been issued yet.</p>;
  }
  if (status === "ACTIVE") {
    return (
      <div className="space-y-1 text-sm">
        <Badge variant="success" dot>Link active</Badge>
        {expiresAt ? (
          <p className="text-foreground-muted">Expires {formatDateTime(expiresAt, tz)}</p>
        ) : null}
      </div>
    );
  }
  if (status === "EXPIRED") {
    return (
      <div className="space-y-1 text-sm">
        <Badge variant="danger" dot>Link expired</Badge>
        <p className="text-foreground-muted">
          {expiresAt ? `Expired ${formatDateTime(expiresAt, tz)}. ` : ""}Resend the invite to generate
          a new one.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-1 text-sm">
      <Badge variant="outline" dot>Link revoked</Badge>
      <p className="text-foreground-muted">A newer link has since been issued.</p>
    </div>
  );
}

function CopyableLink({ label, url, onCopy }: { label: string; url: string; onCopy: () => void }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-info-border bg-info-subtle px-4 py-3 text-sm sm:flex-row sm:items-center">
      <span className="shrink-0 font-medium text-info">{label}</span>
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className="min-w-0 flex-1 truncate text-foreground underline-offset-2 hover:underline"
      >
        {url}
      </a>
      <Button type="button" variant="outline" size="sm" onClick={onCopy} className="shrink-0">
        <Copy className="h-3.5 w-3.5" aria-hidden="true" />
        Copy link
      </Button>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fieldLabel(key: string): string {
  const label = key.replace(/_/g, " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function formatValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map((v) => formatValue(v)).join(", ");
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== null && v !== "")
      .map(([k, v]) => `${fieldLabel(k)}: ${formatValue(v)}`)
      .join(" · ");
  }
  return String(value);
}

function FlatFields({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data).filter(([, value]) => value !== null && value !== "");
  if (entries.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-foreground-muted">
        Not filled in yet.
      </p>
    );
  }
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-4 text-sm sm:grid-cols-2 xl:grid-cols-3">
      {entries.map(([key, value]) => (
        <div key={key} className="min-w-0">
          <dt className="text-xs text-foreground-muted">{fieldLabel(key)}</dt>
          <dd className="mt-0.5 break-words font-medium text-foreground">{formatValue(value)}</dd>
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
      return (
        <p className="rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-foreground-muted">
          None added.
        </p>
      );
    }
    return (
      <div className="space-y-3">
        {items.map((item, index) => (
          <div key={index} className="rounded-md border border-border bg-surface p-4">
            <p className="mb-3 text-xs font-medium uppercase tracking-wide text-foreground-muted">
              Entry {index + 1}
            </p>
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

function DetailRow({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: ReactNode }) {
  const empty = value === null || value === undefined || (typeof value === "string" && !value.trim());
  return (
    <div className="flex min-w-0 items-start gap-3">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-foreground-muted" aria-hidden="true" />
      <div className="min-w-0">
        <dt className="text-xs text-foreground-muted">{label}</dt>
        <dd className={cn("break-words text-sm", empty ? "text-foreground-muted" : "font-medium text-foreground")}>
          {empty ? "Not set" : value}
        </dd>
      </div>
    </div>
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

function nameIn<T extends { id: string; name?: string; title?: string }>(
  list: T[] | undefined,
  id: string | null,
): string {
  if (!id) return "";
  const item = list?.find((entry) => entry.id === id);
  return item?.name ?? item?.title ?? "Unknown";
}

/** One-line hint of what has to happen next, so HR doesn't have to infer it from the status. */
const NEXT_STEP: Record<string, string> = {
  DRAFT: "Compose and send the invitation so the candidate can start filling in their details.",
  INVITED: "Waiting for the candidate to open the link and start the form.",
  IN_PROGRESS: "The candidate is filling in the form. Review opens once they submit.",
  SUBMITTED: "Review each section and document. Verify it, or reject it with a reason.",
  UNDER_REVIEW: "Review each section and document. Verify it, or reject it with a reason.",
  CHANGES_REQUESTED: "Waiting for the candidate to fix the rejected items and resubmit.",
  VERIFIED: "Everything is verified. Activate the case to create the employee record.",
  ACTIVATED: "The employee record has been created.",
  EXPIRED: "The onboarding link expired before the candidate submitted.",
  CANCELLED: "This onboarding case was cancelled.",
};

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
  const [openSections, setOpenSections] = useState<Partial<Record<OnboardingSectionName, boolean>>>({});

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
  const sectionStatus = (section: OnboardingSectionName) =>
    onboardingCase.section_reviews.find((r) => r.section === section)?.status ?? "PENDING";
  const hasUnverified =
    ONBOARDING_SECTION_NAMES.some((section) => {
      const status = sectionStatus(section);
      return status !== "VERIFIED" && status !== "REJECTED";
    }) || (documents ?? []).some((d) => d.status === "PENDING");
  const hasAnyRejection =
    onboardingCase.section_reviews.some((r) => r.status === "REJECTED") ||
    (documents ?? []).some((d) => d.status === "REJECTED");

  const sectionsVerified = ONBOARDING_SECTION_NAMES.filter((s) => sectionStatus(s) === "VERIFIED").length;
  const sectionsRejected = ONBOARDING_SECTION_NAMES.filter((s) => sectionStatus(s) === "REJECTED").length;
  const documentList = documentsError ? [] : (documents ?? []);
  const documentsVerified = documentList.filter((d) => d.status === "VERIFIED").length;
  const documentsRejected = documentList.filter((d) => d.status === "REJECTED").length;
  const reviewTotal = ONBOARDING_SECTION_NAMES.length + documentList.length;
  const reviewDone = sectionsVerified + documentsVerified;
  const nextStep = NEXT_STEP[onboardingCase.status];
  const tz = user?.company_timezone ?? "Asia/Kolkata";
  const designationName = nameIn(refs?.designations, onboardingCase.designation_id);
  const departmentName = nameIn(refs?.departments, onboardingCase.department_id);
  const joiningDate = formatCompanyDate(onboardingCase.proposed_joining_date, datePattern);

  const isSectionOpen = (section: OnboardingSectionName) =>
    openSections[section] ?? sectionStatus(section) !== "VERIFIED";
  const toggleSection = (section: OnboardingSectionName) =>
    setOpenSections((prev) => ({ ...prev, [section]: !isSectionOpen(section) }));

  return (
    <div className="space-y-6">
      <PageHeader
        title={candidateName || "Onboarding case"}
        badge={<OnboardingStatusBadge status={onboardingCase.status} />}
        backHref="/app/onboarding"
        backLabel="Back to onboarding"
        meta={
          <>
            {designationName ? (
              <span className="inline-flex items-center gap-1">
                <Briefcase className="h-3.5 w-3.5" aria-hidden="true" />
                {designationName}
              </span>
            ) : null}
            {departmentName ? (
              <span className="inline-flex items-center gap-1">
                <Layers className="h-3.5 w-3.5" aria-hidden="true" />
                {departmentName}
              </span>
            ) : null}
            {joiningDate ? (
              <span className="inline-flex items-center gap-1">
                <Calendar className="h-3.5 w-3.5" aria-hidden="true" />
                Joins {joiningDate}
              </span>
            ) : null}
          </>
        }
        actions={
          <>
            {canCancel ? (
              <Button type="button" size="sm" variant="outline" onClick={() => setCancelOpen(true)}>
                Cancel Onboarding
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
            {canInvite && isInvitable ? (
              <Button
                type="button"
                size="sm"
                variant={onboardingCase.status === "DRAFT" ? "default" : "outline"}
                onClick={() => setComposerOpen(true)}
              >
                <Mail className="h-3.5 w-3.5" aria-hidden="true" />
                {inviteLabel}
              </Button>
            ) : null}
            {canReview && isReviewable && hasUnverified ? (
              <Button type="button" size="sm" onClick={() => void handleVerifyAll()} disabled={verifyingAll}>
                <BadgeCheck className="h-3.5 w-3.5" aria-hidden="true" />
                {verifyingAll ? "Verifying…" : "Verify All"}
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
                className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
              >
                View employee record
                <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            ) : null}
          </>
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

      {inviteUrl ? <CopyableLink label="Invite link" url={inviteUrl} onCopy={() => void handleCopyLink()} /> : null}
      {loginLinkUrl ? (
        <CopyableLink label="Login setup link" url={loginLinkUrl} onCopy={() => void handleCopyLoginLink()} />
      ) : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Main column: review progress, the candidate's sections and documents. */}
        <div className="min-w-0 space-y-6 lg:col-span-2">
          <Card>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <Clock className="mt-0.5 h-4 w-4 shrink-0 text-foreground-muted" aria-hidden="true" />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">Next step</p>
                    <p className="text-sm text-foreground-secondary">{nextStep}</p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-2xl font-semibold tabular-nums text-foreground">
                    {reviewDone}
                    <span className="text-base font-normal text-foreground-muted">/{reviewTotal}</span>
                  </p>
                  <p className="text-xs text-foreground-muted">items verified</p>
                </div>
              </div>
              <Progress value={reviewDone} max={reviewTotal} aria-label="Review progress" />
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-foreground-muted">
                <span>
                  Sections: {sectionsVerified} of {ONBOARDING_SECTION_NAMES.length} verified
                  {sectionsRejected ? `, ${sectionsRejected} rejected` : ""}
                </span>
                <span>
                  Documents: {documentsVerified} of {documentList.length} verified
                  {documentsRejected ? `, ${documentsRejected} rejected` : ""}
                </span>
              </div>
              <nav aria-label="Jump to section" className="flex flex-wrap gap-2">
                {ONBOARDING_SECTION_NAMES.map((section) => {
                  const status = sectionStatus(section);
                  const Icon = SECTION_ICONS[section];
                  return (
                    <a
                      key={section}
                      href={`#section-${section}`}
                      onClick={() => setOpenSections((prev) => ({ ...prev, [section]: true }))}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors hover:bg-muted",
                        status === "VERIFIED"
                          ? "border-success-border text-success"
                          : status === "REJECTED"
                            ? "border-danger-border text-danger"
                            : "border-border text-foreground-secondary",
                      )}
                    >
                      {status === "VERIFIED" ? (
                        <CircleCheck className="h-3.5 w-3.5" aria-hidden="true" />
                      ) : status === "REJECTED" ? (
                        <CircleAlert className="h-3.5 w-3.5" aria-hidden="true" />
                      ) : (
                        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                      )}
                      {ONBOARDING_SECTION_LABELS[section]}
                    </a>
                  );
                })}
              </nav>
            </CardContent>
          </Card>

          {ONBOARDING_SECTION_NAMES.map((section) => {
            const review = onboardingCase.section_reviews.find((r) => r.section === section);
            const status = review?.status ?? "PENDING";
            const open = isSectionOpen(section);
            const contentId = `section-content-${section}`;
            return (
              <Card key={section} id={`section-${section}`} className="scroll-mt-20">
                <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
                  <button
                    type="button"
                    onClick={() => toggleSection(section)}
                    aria-expanded={open}
                    aria-controls={contentId}
                    className="group flex min-w-0 flex-1 items-center gap-3 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <StatusIcon icon={SECTION_ICONS[section]} status={status} />
                    <h3 className="truncate text-sm font-semibold text-foreground">
                      {ONBOARDING_SECTION_LABELS[section]}
                    </h3>
                    <ReviewStatusBadge status={status} />
                    <ChevronDown
                      className={cn(
                        "h-4 w-4 shrink-0 text-foreground-muted transition-transform group-hover:text-foreground",
                        open ? "rotate-180" : "",
                      )}
                      aria-hidden="true"
                    />
                  </button>
                  {canReview && isReviewable && status !== "VERIFIED" ? (
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={reviewingSection === section}
                        onClick={() => setRejectSection(section)}
                      >
                        Reject
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        disabled={reviewingSection === section}
                        onClick={() => void handleVerifySection(section)}
                      >
                        Verify
                      </Button>
                    </div>
                  ) : null}
                </div>
                <Collapse open={open}>
                  <div id={contentId} className="space-y-4 border-t border-border px-5 py-4">
                    {status === "REJECTED" && review?.rejection_reason ? (
                      <div className="flex items-start gap-2 rounded-md border border-danger-border bg-danger-subtle px-3 py-2 text-sm text-danger">
                        <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                        <p>
                          <span className="font-medium">Rejected:</span> {review.rejection_reason}
                        </p>
                      </div>
                    ) : null}
                    <SectionFields data={onboardingCase[section]} />
                  </div>
                </Collapse>
              </Card>
            );
          })}

          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle className="flex items-center gap-2 text-sm">
                <FileText className="h-4 w-4 text-foreground-muted" aria-hidden="true" />
                Documents
              </CardTitle>
              {documentList.length > 0 ? (
                <span className="text-xs text-foreground-muted">
                  {documentsVerified} of {documentList.length} verified
                </span>
              ) : null}
            </CardHeader>
            <CardContent>
              {documentsError ? (
                <p className="text-sm text-foreground-muted">
                  You do not have permission to view documents, or none have been uploaded yet.
                </p>
              ) : documents === null ? (
                <p role="status" className="text-sm text-foreground-muted">Loading…</p>
              ) : documents.length === 0 ? (
                <p className="rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-foreground-muted">
                  No documents uploaded yet.
                </p>
              ) : (
                <ul className="divide-y divide-border">
                  {documents.map((document) => (
                    <li
                      key={document.id}
                      className="flex flex-col gap-3 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center"
                    >
                      <div className="flex min-w-0 flex-1 items-start gap-3">
                        <StatusIcon icon={FileText} status={document.status} />
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-foreground">
                            {ONBOARDING_DOCUMENT_TYPE_LABELS[
                              document.document_type as keyof typeof ONBOARDING_DOCUMENT_TYPE_LABELS
                            ] ?? document.document_type}
                          </p>
                          <a
                            href={document.download_url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex max-w-full items-center gap-1 text-xs text-foreground-secondary underline-offset-2 hover:text-foreground hover:underline"
                          >
                            <span className="truncate">{document.original_filename}</span>
                            <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />
                          </a>
                          <span className="ml-2 text-xs text-foreground-muted">
                            {formatBytes(document.size_bytes)}
                          </span>
                          {document.status === "REJECTED" && document.rejection_reason ? (
                            <p className="mt-1 text-xs text-danger">Rejected: {document.rejection_reason}</p>
                          ) : null}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 sm:justify-end">
                        <ReviewStatusBadge status={document.status} />
                        {canReview ? (
                          <>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={reviewingDocumentId === document.id}
                              onClick={() => setRejectDocument(document)}
                            >
                              Reject
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={reviewingDocumentId === document.id}
                              onClick={() => void handleVerifyDocument(document)}
                            >
                              Verify
                            </Button>
                          </>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Sidebar: who the candidate is, the role they're joining, and the invitation trail. */}
        <aside className="min-w-0 space-y-6">
          <Card>
            <CardContent className="space-y-5">
              <div className="flex items-center gap-3">
                <span
                  aria-hidden="true"
                  className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary-subtle text-base font-semibold text-primary"
                >
                  {initials(candidateName)}
                </span>
                <div className="min-w-0">
                  <p className="truncate font-semibold text-foreground">{candidateName || "Unnamed candidate"}</p>
                  <p className="text-xs text-foreground-muted">Candidate</p>
                </div>
              </div>
              <dl className="space-y-3">
                <DetailRow icon={User} label="First name" value={onboardingCase.candidate_first_name} />
                <DetailRow icon={User} label="Last name" value={onboardingCase.candidate_last_name} />
                <DetailRow icon={Mail} label="Personal email" value={onboardingCase.personal_email} />
                <DetailRow icon={Phone} label="Personal mobile" value={onboardingCase.personal_mobile} />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Joining details</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="space-y-3">
                <DetailRow icon={Calendar} label="Proposed joining date" value={joiningDate} />
                <DetailRow
                  icon={Building2}
                  label="Company"
                  value={nameIn(refs?.legalEntities, onboardingCase.legal_entity_id)}
                />
                <DetailRow icon={GitBranch} label="Branch" value={nameIn(refs?.branches, onboardingCase.branch_id)} />
                <DetailRow icon={Layers} label="Department" value={departmentName} />
                <DetailRow icon={Briefcase} label="Designation" value={designationName} />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Onboarding link</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <LinkStatus status={onboardingCase.token_status} expiresAt={onboardingCase.token_expires_at} tz={tz} />
              {canInvite || can("ONBOARDING.VIEW") ? (
                <InvitationHistory
                  caseId={onboardingCase.id}
                  currentUserId={user?.id}
                  refreshKey={historyKey}
                  canResend={canInvite && isInvitable}
                  onResend={() => setComposerOpen(true)}
                />
              ) : null}
            </CardContent>
          </Card>

          {onboardingCase.face_enrollment_required ? (
            <Card>
              <CardContent className="flex items-start gap-3">
                <StatusIcon
                  icon={ScanFace}
                  status={onboardingCase.face_enrollment?.requirement_met ? "VERIFIED" : "PENDING"}
                />
                <div className="min-w-0 space-y-1">
                  <h3 className="text-sm font-semibold text-foreground">Face enrollment</h3>
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
                    <p className="text-sm text-foreground-muted">Available after the employee is activated.</p>
                  )}
                </div>
              </CardContent>
            </Card>
          ) : null}
        </aside>
      </div>

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
