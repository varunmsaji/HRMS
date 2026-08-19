"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AttendancePolicyForm } from "@/components/attendance-policy/attendance-policy-form";
import { AttendancePolicyVersionForm } from "@/components/attendance-policy/attendance-policy-version-form";
import { ConcurrencyConflictBanner } from "@/components/employee/concurrency-conflict-banner";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { PolicyVersionPublishDialog } from "@/components/common/policy-version-publish-dialog";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { AttendancePolicy, AttendancePolicyVersion } from "@/lib/attendance-policy/types";
import {
  buildAttendancePolicyUpdatePatch,
  buildAttendancePolicyVersionPayload,
  attendancePolicyVersionToFormValues,
  mapAttendancePolicyVersionApiErrors,
  validateAttendancePolicyForm,
  validateAttendancePolicyVersionForm,
  type AttendancePolicyFormErrors,
  type AttendancePolicyFormValues,
  type AttendancePolicyVersionFormErrors,
  type AttendancePolicyVersionFormValues,
} from "@/lib/attendance-policy/validate-attendance-policy";

type TabKey = "overview" | "versions";
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "versions", label: "Versions" },
];

export default function AttendancePolicyDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("ATTENDANCE.POLICY_MANAGE");

  const [tab, setTab] = useState<TabKey>("overview");

  const [policy, setPolicy] = useState<AttendancePolicy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<AttendancePolicyFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<AttendancePolicyFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [statusChanging, setStatusChanging] = useState(false);

  const [versions, setVersions] = useState<AttendancePolicyVersion[] | null>(null);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [creatingDraft, setCreatingDraft] = useState(false);

  const [draftValues, setDraftValues] = useState<AttendancePolicyVersionFormValues | null>(null);
  const [draftErrors, setDraftErrors] = useState<AttendancePolicyVersionFormErrors>({});
  const [savingDraft, setSavingDraft] = useState(false);
  const [draftStaleMessage, setDraftStaleMessage] = useState<string | null>(null);

  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [publishDialogOpen, setPublishDialogOpen] = useState(false);

  const draft = versions?.find((v) => v.status === "DRAFT") ?? null;
  const currentPublished =
    versions?.find((v) => v.status === "PUBLISHED" && v.effective_to === null) ?? null;
  const historical =
    versions
      ?.filter((v) => v.id !== draft?.id && v.id !== currentPublished?.id)
      .sort((a, b) => (b.effective_from ?? "").localeCompare(a.effective_from ?? "")) ?? [];

  const loadPolicy = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<AttendancePolicy>(`/attendance-policies/${params.id}`);
      setPolicy(data);
      return data;
    } catch (err) {
      setPolicy(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
      return null;
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  const loadVersions = useCallback(async () => {
    setVersionsLoading(true);
    try {
      const data = await apiClient.get<AttendancePolicyVersion[]>(
        `/attendance-policies/${params.id}/versions`,
      );
      setVersions(data);
      return data;
    } catch (err) {
      toast({
        title: "Could not load policy versions",
        description: describeApiError(err),
        variant: "danger",
      });
      return null;
    } finally {
      setVersionsLoading(false);
    }
  }, [params.id, toast]);

  useEffect(() => {
    void loadPolicy();
  }, [loadPolicy]);

  useEffect(() => {
    if (tab === "versions" && versions === null) {
      void loadVersions();
    }
  }, [tab, versions, loadVersions]);

  function startEditing() {
    if (!policy) return;
    setFormValues({ name: policy.name, code: policy.code ?? "" });
    setFormErrors({});
    setStaleMessage(null);
    setEditing(true);
  }

  function cancelEditing() {
    setEditing(false);
    setFormValues(null);
    setFormErrors({});
    setStaleMessage(null);
  }

  async function handleSave() {
    if (!policy || !formValues) return;
    const clientErrors = validateAttendancePolicyForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }
    const patch = buildAttendancePolicyUpdatePatch(formValues, policy);
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      setFormValues(null);
      toast({ title: "No changes to save", variant: "default" });
      return;
    }
    setSaving(true);
    setFormErrors({});
    setStaleMessage(null);
    try {
      const updated = await apiClient.patch<AttendancePolicy>(
        `/attendance-policies/${policy.id}`,
        patch,
        { ifMatch: String(policy.version) },
      );
      setPolicy(updated);
      setEditing(false);
      setFormValues(null);
      toast({ title: "Policy saved", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("This policy was changed by someone else.");
          return;
        }
        if (err.status === 422) {
          setFormErrors({ name: getFieldError(err.details, "name") });
          return;
        }
        if (err.status === 403) {
          setError(err);
          setEditing(false);
          return;
        }
      }
      toast({ title: "Could not save policy", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatest() {
    const latest = await loadPolicy();
    if (latest) {
      setEditing(false);
      setFormValues(null);
      setStaleMessage(null);
      toast({ title: "Reloaded", variant: "success" });
    }
  }

  async function handleToggleStatus() {
    if (!policy) return;
    setStatusChanging(true);
    try {
      const updated = await apiClient.patch<AttendancePolicy>(
        `/attendance-policies/${policy.id}`,
        { is_active: !policy.is_active },
        { ifMatch: String(policy.version) },
      );
      setPolicy(updated);
      toast({ title: updated.is_active ? "Policy reactivated" : "Policy deactivated", variant: "success" });
      setConfirmOpen(false);
    } catch (err) {
      toast({
        title: "Could not update policy status",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setStatusChanging(false);
    }
  }

  function startEditingDraft() {
    if (!draft) return;
    setDraftValues(attendancePolicyVersionToFormValues(draft));
    setDraftErrors({});
    setDraftStaleMessage(null);
  }

  useEffect(() => {
    if (draft && draftValues === null) startEditingDraft();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.id]);

  async function handleCreateDraft() {
    setCreatingDraft(true);
    try {
      await apiClient.post(`/attendance-policies/${params.id}/versions`, {});
      toast({ title: "Draft created", variant: "success" });
      await loadVersions();
    } catch (err) {
      toast({
        title: "Could not create a new draft",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setCreatingDraft(false);
    }
  }

  async function handleSaveDraft() {
    if (!draft || !draftValues) return;
    const clientErrors = validateAttendancePolicyVersionForm(draftValues);
    if (Object.keys(clientErrors).length > 0) {
      setDraftErrors(clientErrors);
      toast({ title: "Fix the highlighted fields", variant: "danger" });
      return;
    }
    setSavingDraft(true);
    setDraftErrors({});
    setDraftStaleMessage(null);
    try {
      const payload = buildAttendancePolicyVersionPayload(draftValues);
      const updated = await apiClient.patch<AttendancePolicyVersion>(
        `/attendance-policies/${params.id}/versions/${draft.id}`,
        payload,
        { ifMatch: String(draft.version) },
      );
      setVersions((prev) => (prev ? prev.map((v) => (v.id === updated.id ? updated : v)) : prev));
      setDraftValues(attendancePolicyVersionToFormValues(updated));
      toast({ title: "Draft saved", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setDraftStaleMessage("This draft was changed by someone else.");
          return;
        }
        if (err.status === 422) {
          setDraftErrors(mapAttendancePolicyVersionApiErrors(err.details));
          return;
        }
      }
      toast({ title: "Could not save draft", description: describeApiError(err), variant: "danger" });
    } finally {
      setSavingDraft(false);
    }
  }

  async function reloadDraftLatest() {
    const latest = await loadVersions();
    if (latest) {
      setDraftStaleMessage(null);
      const latestDraft = latest.find((v) => v.status === "DRAFT") ?? null;
      setDraftValues(latestDraft ? attendancePolicyVersionToFormValues(latestDraft) : null);
      toast({ title: "Reloaded", variant: "success" });
    }
  }

  async function handleDiscardDraft() {
    if (!draft) return;
    setDiscarding(true);
    try {
      await apiClient.delete(`/attendance-policies/${params.id}/versions/${draft.id}`, {
        ifMatch: String(draft.version),
      });
      setDiscardConfirmOpen(false);
      setDraftValues(null);
      toast({ title: "Draft discarded", variant: "success" });
      await loadVersions();
    } catch (err) {
      toast({
        title: "Could not discard draft",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setDiscarding(false);
    }
  }

  function handlePublished() {
    setDraftValues(null);
    toast({ title: "Policy published", variant: "success" });
    void loadVersions();
  }

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/app/attendance-policies"
          className="text-sm text-foreground-secondary hover:underline"
        >
          ← Attendance Policies
        </Link>
      </div>

      <PageHeader
        title={policy?.name ?? "Attendance Policy"}
        description="Identity on the Overview tab; grace/rounding/band rules live on the Versions tab."
        actions={
          canManage && policy && !editing && tab === "overview" ? (
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)}>
                {policy.is_active ? "Deactivate" : "Reactivate"}
              </Button>
              <Button type="button" onClick={startEditing}>
                Edit
              </Button>
            </div>
          ) : null
        }
      />

      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label="Loading policy…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this policy."
                  : error.status === 404
                    ? "This policy could not be found."
                    : error.message
              }
              onRetry={error.status === 404 ? undefined : () => void loadPolicy()}
            />
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && policy ? (
        <>
          <div className="flex gap-1 overflow-x-auto border-b border-border" role="tablist">
            {TABS.map((item) => (
              <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={tab === item.key}
                onClick={() => setTab(item.key)}
                className={`shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                  tab === item.key
                    ? "border-primary text-foreground"
                    : "border-transparent text-foreground-muted hover:text-foreground"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          {tab === "overview" ? (
            <Card>
              <CardContent className="pt-6">
                {staleMessage ? (
                  <ConcurrencyConflictBanner
                    message={staleMessage}
                    onReload={() => void reloadLatest()}
                    onCancel={cancelEditing}
                  />
                ) : null}

                {editing && formValues ? (
                  <div className="space-y-6">
                    <AttendancePolicyForm
                      values={formValues}
                      errors={formErrors}
                      onChange={setFormValues}
                    />
                    <div className="flex flex-wrap gap-2">
                      <Button type="button" onClick={() => void handleSave()} disabled={saving}>
                        {saving ? "Saving…" : "Save changes"}
                      </Button>
                      <Button type="button" variant="outline" onClick={cancelEditing} disabled={saving}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <Badge variant={policy.is_active ? "secondary" : "outline"}>
                      {policy.is_active ? "Active" : "Inactive"}
                    </Badge>
                    <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div>
                        <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                          Policy name
                        </dt>
                        <dd className="mt-0.5 text-sm text-foreground">{policy.name}</dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                          Policy code
                        </dt>
                        <dd className="mt-0.5 text-sm text-foreground">{policy.code ?? "—"}</dd>
                      </div>
                    </dl>
                    <p className="text-xs text-foreground-muted">
                      Configure grace, rounding, and bands on the{" "}
                      <button type="button" className="underline" onClick={() => setTab("versions")}>
                        Versions tab
                      </button>
                      .
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          ) : null}

          {tab === "versions" ? (
            <div className="space-y-6">
              {versionsLoading && versions === null ? (
                <Card>
                  <CardContent className="pt-6">
                    <LoadingState label="Loading versions…" />
                  </CardContent>
                </Card>
              ) : null}

              {versions !== null ? (
                <>
                  <Card>
                    <CardContent className="space-y-4 pt-6">
                      <h3 className="text-sm font-medium text-foreground">Currently published</h3>
                      {currentPublished ? (
                        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                          <div>
                            <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                              Effective from
                            </dt>
                            <dd className="mt-0.5 text-sm text-foreground">
                              {currentPublished.effective_from}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                              Grace in / out
                            </dt>
                            <dd className="mt-0.5 text-sm text-foreground">
                              {currentPublished.grace_in_minutes}m / {currentPublished.grace_out_minutes}m
                            </dd>
                          </div>
                          <div>
                            <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                              Hour bands
                            </dt>
                            <dd className="mt-0.5 text-sm text-foreground">
                              {currentPublished.hour_bands.length} configured
                            </dd>
                          </div>
                        </dl>
                      ) : (
                        <p className="text-sm text-foreground-muted">
                          No published version yet — resolution will report CONFIG_INCOMPLETE for
                          anyone assigned this policy until a draft is published.
                        </p>
                      )}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardContent className="space-y-4 pt-6">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-medium text-foreground">Draft</h3>
                        {canManage && !draft ? (
                          <Button
                            type="button"
                            size="sm"
                            onClick={() => void handleCreateDraft()}
                            disabled={creatingDraft}
                          >
                            {creatingDraft ? "Creating…" : "New draft"}
                          </Button>
                        ) : null}
                      </div>

                      {!draft ? (
                        <p className="text-sm text-foreground-muted">
                          No open draft. Start one to change this policy&apos;s rules.
                        </p>
                      ) : null}

                      {draft && draftValues ? (
                        <div className="space-y-6">
                          {draftStaleMessage ? (
                            <ConcurrencyConflictBanner
                              message={draftStaleMessage}
                              onReload={() => void reloadDraftLatest()}
                              onCancel={() => setDraftStaleMessage(null)}
                            />
                          ) : null}
                          <AttendancePolicyVersionForm
                            values={draftValues}
                            errors={draftErrors}
                            onChange={setDraftValues}
                          />
                          <div className="flex flex-wrap gap-2">
                            {canManage ? (
                              <>
                                <Button
                                  type="button"
                                  onClick={() => void handleSaveDraft()}
                                  disabled={savingDraft}
                                >
                                  {savingDraft ? "Saving…" : "Save draft"}
                                </Button>
                                <Button
                                  type="button"
                                  onClick={() => setPublishDialogOpen(true)}
                                  disabled={savingDraft}
                                >
                                  Publish…
                                </Button>
                                <Button
                                  type="button"
                                  variant="outline"
                                  onClick={() => setDiscardConfirmOpen(true)}
                                  disabled={savingDraft}
                                >
                                  Discard draft
                                </Button>
                              </>
                            ) : null}
                          </div>
                        </div>
                      ) : null}
                    </CardContent>
                  </Card>

                  {historical.length > 0 ? (
                    <Card>
                      <CardContent className="pt-6">
                        <h3 className="text-sm font-medium text-foreground">History</h3>
                        <ul className="mt-3 divide-y divide-border">
                          {historical.map((version) => (
                            <li key={version.id} className="py-3 first:pt-0 last:pb-0">
                              <p className="text-sm font-medium text-foreground">
                                Grace {version.grace_in_minutes}m / {version.grace_out_minutes}m —{" "}
                                {version.hour_bands.length} hour bands
                              </p>
                              <p className="mt-0.5 text-xs text-foreground-muted">
                                {version.effective_from} – {version.effective_to ?? "open"}
                              </p>
                            </li>
                          ))}
                        </ul>
                      </CardContent>
                    </Card>
                  ) : null}
                </>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}

      <Dialog open={confirmOpen} onOpenChange={(open) => (!statusChanging ? setConfirmOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{policy?.is_active ? "Deactivate policy?" : "Reactivate policy?"}</DialogTitle>
            <DialogDescription>
              {policy?.is_active
                ? "This policy will no longer be assignable to a new scope. Existing assignments are unaffected."
                : "This policy becomes assignable again."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setConfirmOpen(false)} disabled={statusChanging}>
              Cancel
            </Button>
            <Button
              type="button"
              variant={policy?.is_active ? "destructive" : "default"}
              onClick={() => void handleToggleStatus()}
              disabled={statusChanging}
            >
              {statusChanging ? "Saving…" : policy?.is_active ? "Deactivate" : "Reactivate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={discardConfirmOpen}
        onOpenChange={(open) => (!discarding ? setDiscardConfirmOpen(open) : null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Discard this draft?</DialogTitle>
            <DialogDescription>
              This removes the unpublished changes. The currently published version (if any) is
              unaffected.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDiscardConfirmOpen(false)}
              disabled={discarding}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void handleDiscardDraft()}
              disabled={discarding}
            >
              {discarding ? "Discarding…" : "Discard draft"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {draft ? (
        <PolicyVersionPublishDialog
          open={publishDialogOpen}
          onOpenChange={setPublishDialogOpen}
          versionsPath={`/attendance-policies/${params.id}/versions`}
          draft={draft}
          currentPublished={currentPublished}
          onPublished={handlePublished}
          onStale={(message) => {
            setPublishDialogOpen(false);
            setDraftStaleMessage(message);
          }}
        />
      ) : null}
    </div>
  );
}
