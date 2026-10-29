"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
import { DocumentRejectDialog } from "@/components/employee/document-reject-dialog";
import { Badge } from "@/components/ui/badge";
import { HorizontalScroll } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  EMPLOYEE_DOCUMENT_TYPES,
  EMPLOYEE_DOCUMENT_TYPE_LABELS,
  type EmployeeDocument,
  type EmployeeDocumentType,
} from "@/lib/employee/types";

interface DocumentPanelProps {
  employeeId: string;
}

function ReviewStatusBadge({ status }: { status: string }) {
  if (status === "VERIFIED") return <Badge variant="success">Verified</Badge>;
  if (status === "REJECTED") return <Badge variant="danger">Rejected</Badge>;
  return <Badge variant="outline">Pending</Badge>;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentPanel({ employeeId }: DocumentPanelProps) {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("EMPLOYEE.UPDATE_SENSITIVE");

  const [documents, setDocuments] = useState<EmployeeDocument[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [documentType, setDocumentType] = useState<EmployeeDocumentType | "">("");
  const [uploading, setUploading] = useState(false);
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [rejectDocument, setRejectDocument] = useState<EmployeeDocument | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // SELF-scoped per `EMPLOYEE.VIEW_DOCUMENTS` — the backend, not this component, decides
      // whether the caller sees only their own documents or the whole company's.
      const data = await apiClient.get<EmployeeDocument[]>(`/employees/${employeeId}/documents`);
      setDocuments(data);
    } catch (err) {
      setDocuments(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [employeeId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleUpload() {
    const file = fileInputRef.current?.files?.[0];
    if (!documentType) {
      toast({ title: "Choose a document type first", variant: "danger" });
      return;
    }
    if (!file) {
      toast({ title: "Choose a file first", variant: "danger" });
      return;
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.set("document_type", documentType);
      formData.set("file", file);
      await apiClient.post(`/employees/${employeeId}/documents`, formData);
      setDocumentType("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      toast({ title: "Document uploaded", variant: "success" });
      await load();
    } catch (err) {
      const message =
        err instanceof ApiError && err.status === 422 ? err.message : describeApiError(err);
      toast({ title: "Could not upload document", description: message, variant: "danger" });
    } finally {
      setUploading(false);
    }
  }

  async function handleVerify(document: EmployeeDocument) {
    setReviewingId(document.id);
    try {
      const updated = await apiClient.post<EmployeeDocument>(
        `/employees/${employeeId}/documents/${document.id}/review`,
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

  async function handleDelete(document: EmployeeDocument) {
    setDeletingId(document.id);
    try {
      await apiClient.delete(`/employees/${employeeId}/documents/${document.id}`);
      setDocuments((prev) => (prev ?? []).filter((d) => d.id !== document.id));
      toast({ title: "Document removed", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        toast({ title: "You don't have permission to remove this document", variant: "danger" });
        return;
      }
      toast({ title: "Could not remove document", description: describeApiError(err), variant: "danger" });
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="space-y-6">
      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label="Loading documents…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this employee's documents."
                  : error.message
              }
              onRetry={() => void load()}
            />
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && documents ? (
        <Card>
          <CardContent className="space-y-4 pt-6">
            <h3 className="text-sm font-medium text-foreground">Documents</h3>

            {documents.length === 0 ? (
              <EmptyState
                title="No documents on record yet."
                description="Documents collected during onboarding appear here automatically once the case is activated. HR can also add documents directly at any time."
              />
            ) : (
              <HorizontalScroll>
                <table className="w-full min-w-[560px] border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wide text-foreground-muted">
                      <th className="py-2 pr-4">Type</th>
                      <th className="py-2 pr-4">File</th>
                      <th className="py-2 pr-4">Size</th>
                      <th className="py-2 pr-4">Status</th>
                      {canManage ? <th className="py-2 pr-0">Actions</th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {documents.map((document) => (
                      <tr key={document.id} className="border-b border-border last:border-0">
                        <td className="py-3 pr-4 text-foreground-secondary">
                          {EMPLOYEE_DOCUMENT_TYPE_LABELS[
                            document.document_type as EmployeeDocumentType
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
                        <td className="py-3 pr-4 text-foreground-secondary">
                          {formatBytes(document.size_bytes)}
                        </td>
                        <td className="py-3 pr-4">
                          <ReviewStatusBadge status={document.status} />
                          {document.status === "REJECTED" && document.rejection_reason ? (
                            <p className="mt-1 text-xs text-foreground-muted">{document.rejection_reason}</p>
                          ) : null}
                        </td>
                        {canManage ? (
                          <td className="py-3 pr-0">
                            <div className="flex flex-wrap gap-2">
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
                                onClick={() => setRejectDocument(document)}
                              >
                                Reject
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                disabled={deletingId === document.id}
                                onClick={() => void handleDelete(document)}
                              >
                                {deletingId === document.id ? "Removing…" : "Remove"}
                              </Button>
                            </div>
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </HorizontalScroll>
            )}

            {canManage ? (
              <div className="grid grid-cols-1 gap-4 border-t border-border pt-4 sm:grid-cols-2">
                <FormField id="employeeDocumentType" label="Document type">
                  <NativeSelect
                    value={documentType}
                    onChange={(e) => setDocumentType(e.target.value as EmployeeDocumentType | "")}
                  >
                    <option value="">Select a document type</option>
                    {EMPLOYEE_DOCUMENT_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {EMPLOYEE_DOCUMENT_TYPE_LABELS[type]}
                      </option>
                    ))}
                  </NativeSelect>
                </FormField>
                <FormField id="employeeDocumentFile" label="File">
                  <input
                    ref={fileInputRef}
                    id="employeeDocumentFile"
                    type="file"
                    className="block w-full text-sm text-foreground file:mr-3 file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:py-1.5 file:text-sm"
                  />
                </FormField>
                <div className="flex items-end sm:col-span-2 sm:justify-end">
                  <Button type="button" variant="outline" disabled={uploading} onClick={() => void handleUpload()}>
                    {uploading ? "Uploading…" : "Upload"}
                  </Button>
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <DocumentRejectDialog
        open={rejectDocument !== null}
        onOpenChange={(open) => (!open ? setRejectDocument(null) : null)}
        employeeId={employeeId}
        document={rejectDocument}
        onDone={(updated) => {
          setDocuments((prev) => (prev ?? []).map((d) => (d.id === updated.id ? updated : d)));
          setRejectDocument(null);
        }}
      />
    </div>
  );
}
