"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { DocumentRejectDialog } from "@/components/onboarding/document-review-dialog";
import { OnboardingStatusBadge } from "@/components/onboarding/onboarding-status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import type { LegalEntity } from "@/lib/legal-entity/types";
import {
  ONBOARDING_CASE_INVITABLE_STATUSES,
  ONBOARDING_DOCUMENT_TYPE_LABELS,
  type OnboardingCase,
  type OnboardingDocumentWithUrl,
  type OnboardingInvite,
} from "@/lib/onboarding/types";

function DocumentStatusBadge({ status }: { status: string }) {
  if (status === "VERIFIED") return <Badge variant="success">Verified</Badge>;
  if (status === "REJECTED") return <Badge variant="danger">Rejected</Badge>;
  return <Badge variant="outline">Pending</Badge>;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</dt>
      <dd className={`mt-0.5 text-sm ${value && value.trim() ? "text-foreground" : "text-foreground-muted"}`}>
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

export default function OnboardingCaseDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const { can } = usePermissions();

  const [onboardingCase, setOnboardingCase] = useState<OnboardingCase | null>(null);
  const [refs, setRefs] = useState<ReferenceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [sendingInvite, setSendingInvite] = useState(false);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);

  const [documents, setDocuments] = useState<OnboardingDocumentWithUrl[] | null>(null);
  const [documentsError, setDocumentsError] = useState(false);
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [rejectTarget, setRejectTarget] = useState<OnboardingDocumentWithUrl | null>(null);

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
        apiClient.get<OnboardingCase>(`/onboarding-cases/${params.id}`),
        apiClient.get<Branch[]>("/branches").catch(() => []),
        apiClient.get<Department[]>("/departments").catch(() => []),
        apiClient.get<Designation[]>("/designations").catch(() => []),
        apiClient.get<LegalEntity[]>("/legal-entities").catch(() => []),
      ]);
      setOnboardingCase(data);
      setRefs({ branches, departments, designations, legalEntities });
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

  async function handleVerify(document: OnboardingDocumentWithUrl) {
    setReviewingId(document.id);
    try {
      const updated = await apiClient.post<OnboardingDocumentWithUrl>(
        `/onboarding-cases/${params.id}/documents/${document.id}/review`,
        { status: "VERIFIED" },
      );
      setDocuments((prev) =>
        (prev ?? []).map((d) => (d.id === document.id ? { ...updated, download_url: d.download_url } : d)),
      );
      toast({ title: "Document verified", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        toast({ title: "You don't have permission to review this document", variant: "danger" });
        return;
      }
      toast({ title: "Could not verify document", description: describeApiError(err), variant: "danger" });
    } finally {
      setReviewingId(null);
    }
  }

  async function handleSendInvite() {
    setSendingInvite(true);
    try {
      const result = await apiClient.post<OnboardingInvite>(
        `/onboarding-cases/${params.id}/send-invite`,
      );
      setOnboardingCase(result.case);
      setInviteUrl(result.invite_url);
      toast({
        title: result.email_sent ? "Invite sent" : "Invite link created",
        description: result.email_sent
          ? `An email was sent to ${result.case.personal_email}.`
          : "The link is ready to copy — email delivery isn't configured in this environment.",
        variant: "success",
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        toast({ title: "You don't have permission to send this invite", variant: "danger" });
        return;
      }
      toast({ title: "Could not send invite", description: describeApiError(err), variant: "danger" });
    } finally {
      setSendingInvite(false);
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
  const isInvitable = ONBOARDING_CASE_INVITABLE_STATUSES.includes(onboardingCase.status);
  const inviteLabel = onboardingCase.status === "DRAFT" ? "Send Invite" : "Resend Invite";

  return (
    <div className="space-y-6">
      <PageHeader
        title={candidateName || "Onboarding case"}
        description="HR-started onboarding case — sending the candidate link, section review, and activation land in later phases."
        actions={
          <Link href="/app/onboarding" className="text-sm text-foreground-secondary hover:underline">
            ← Back to onboarding
          </Link>
        }
      />

      <Card>
        <CardContent className="space-y-6 pt-6">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-foreground">Status</h3>
            <div className="flex items-center gap-3">
              <OnboardingStatusBadge status={onboardingCase.status} />
              {canInvite && isInvitable ? (
                <Button type="button" size="sm" onClick={() => void handleSendInvite()} disabled={sendingInvite}>
                  {sendingInvite ? "Sending…" : inviteLabel}
                </Button>
              ) : null}
            </div>
          </div>

          {inviteUrl ? (
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-background-secondary px-3 py-2 text-sm">
              <span className="text-foreground-muted">Invite link:</span>
              <code className="truncate text-foreground">{inviteUrl}</code>
              <Button type="button" variant="outline" size="sm" onClick={() => void handleCopyLink()}>
                Copy link
              </Button>
            </div>
          ) : null}

          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <DetailField label="Candidate first name" value={onboardingCase.candidate_first_name} />
            <DetailField label="Candidate last name" value={onboardingCase.candidate_last_name} />
            <DetailField label="Personal email" value={onboardingCase.personal_email} />
            <DetailField label="Personal mobile" value={onboardingCase.personal_mobile} />
            <DetailField label="Proposed joining date" value={onboardingCase.proposed_joining_date} />
            <DetailField label="Legal entity" value={nameIn(refs?.legalEntities, onboardingCase.legal_entity_id)} />
            <DetailField label="Branch" value={nameIn(refs?.branches, onboardingCase.branch_id)} />
            <DetailField label="Department" value={nameIn(refs?.departments, onboardingCase.department_id)} />
            <DetailField label="Designation" value={nameIn(refs?.designations, onboardingCase.designation_id)} />
          </dl>
        </CardContent>
      </Card>

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
            <div className="overflow-x-auto">
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
                        <DocumentStatusBadge status={document.status} />
                        {document.status === "REJECTED" && document.rejection_reason ? (
                          <p className="mt-1 text-xs text-foreground-muted">{document.rejection_reason}</p>
                        ) : null}
                      </td>
                      <td className="py-3 pr-0">
                        {can("ONBOARDING.REVIEW") ? (
                          <div className="flex gap-2">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={reviewingId === document.id}
                              onClick={() => void handleVerify(document)}
                            >
                              Verify
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={reviewingId === document.id}
                              onClick={() => setRejectTarget(document)}
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
            </div>
          ) : null}
        </CardContent>
      </Card>

      <DocumentRejectDialog
        open={rejectTarget !== null}
        onOpenChange={(open) => (!open ? setRejectTarget(null) : null)}
        caseId={params.id}
        document={rejectTarget}
        onDone={(updated) => {
          setDocuments((prev) => (prev ?? []).map((d) => (d.id === updated.id ? updated : d)));
          setRejectTarget(null);
        }}
      />
    </div>
  );
}
