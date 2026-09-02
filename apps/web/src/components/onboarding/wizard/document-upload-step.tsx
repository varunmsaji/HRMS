"use client";

import { useRef, useState } from "react";

import { FormField } from "@/components/common/form-field";
import { useToast } from "@/components/common/toast";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import {
  ONBOARDING_DOCUMENT_TYPES,
  ONBOARDING_DOCUMENT_TYPE_LABELS,
  type OnboardingDocument,
  type OnboardingDocumentType,
} from "@/lib/onboarding/types";

interface DocumentUploadStepProps {
  token: string;
  documents: OnboardingDocument[];
  onDocumentsChange: (documents: OnboardingDocument[]) => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentUploadStep({ token, documents, onDocumentsChange }: DocumentUploadStepProps) {
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [documentType, setDocumentType] = useState<OnboardingDocumentType | "">("");
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

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
      const created = await apiClient.post<OnboardingDocument>(
        `/public/onboarding/${token}/documents`,
        formData,
        { authenticated: false },
      );
      onDocumentsChange([...documents, created]);
      setDocumentType("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      toast({ title: "Document uploaded", variant: "success" });
    } catch (err) {
      const message =
        err instanceof ApiError && err.status === 422
          ? err.message
          : describeApiError(err);
      toast({ title: "Could not upload document", description: message, variant: "danger" });
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(documentId: string) {
    setDeletingId(documentId);
    try {
      await apiClient.delete(`/public/onboarding/${token}/documents/${documentId}`, {
        authenticated: false,
      });
      onDocumentsChange(documents.filter((d) => d.id !== documentId));
    } catch (err) {
      toast({ title: "Could not remove document", description: describeApiError(err), variant: "danger" });
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-foreground-secondary">
        Upload clear photos or scans of your ID and any other requested documents. You can remove
        and re-upload anything below before submitting.
      </p>

      {documents.length > 0 ? (
        <ul className="space-y-2">
          {documents.map((document) => (
            <li
              key={document.id}
              className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm"
            >
              <div>
                <span className="font-medium text-foreground">
                  {ONBOARDING_DOCUMENT_TYPE_LABELS[document.document_type as OnboardingDocumentType] ??
                    document.document_type}
                </span>
                <span className="ml-2 text-foreground-muted">
                  {document.original_filename} · {formatBytes(document.size_bytes)}
                </span>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={deletingId === document.id}
                onClick={() => void handleDelete(document.id)}
              >
                {deletingId === document.id ? "Removing…" : "Remove"}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField id="documentType" label="Document type">
          <NativeSelect
            value={documentType}
            onChange={(e) => setDocumentType(e.target.value as OnboardingDocumentType | "")}
          >
            <option value="">Select a document type</option>
            {ONBOARDING_DOCUMENT_TYPES.map((type) => (
              <option key={type} value={type}>
                {ONBOARDING_DOCUMENT_TYPE_LABELS[type]}
              </option>
            ))}
          </NativeSelect>
        </FormField>
        <FormField id="documentFile" label="File">
          <input
            ref={fileInputRef}
            id="documentFile"
            type="file"
            className="block w-full text-sm text-foreground file:mr-3 file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:py-1.5 file:text-sm"
          />
        </FormField>
      </div>
      <div className="flex justify-end">
        <Button type="button" variant="outline" disabled={uploading} onClick={() => void handleUpload()}>
          {uploading ? "Uploading…" : "Upload"}
        </Button>
      </div>
    </div>
  );
}
