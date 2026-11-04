"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ConcurrencyConflictBanner } from "@/components/employee/concurrency-conflict-banner";
import { CompanyDate } from "@/components/common/company-date";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { PolicyVersionPublishDialog } from "@/components/common/policy-version-publish-dialog";
import { useToast } from "@/components/common/toast";
import { RegularizationPolicyForm } from "@/components/regularization-policy/regularization-policy-form";
import { RegularizationPolicyVersionForm } from "@/components/regularization-policy/regularization-policy-version-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableToolbar,
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type {
  RegularizationPolicy,
  RegularizationPolicyVersion,
} from "@/lib/regularization-policy/types";
import {
  EMPTY_REGULARIZATION_POLICY_VERSION_FORM_VALUES,
  buildRegularizationPolicyUpdatePatch,
  buildRegularizationPolicyVersionPayload,
  regularizationPolicyVersionToFormValues,
  mapRegularizationPolicyVersionApiErrors,
  validateRegularizationPolicyForm,
  validateRegularizationPolicyVersionForm,
  type RegularizationPolicyFormErrors,
  type RegularizationPolicyFormValues,
  type RegularizationPolicyVersionFormErrors,
  type RegularizationPolicyVersionFormValues,
} from "@/lib/regularization-policy/validate-regularization-policy";
import { cn } from "@/lib/utils";

type TabKey = "overview" | "versions";
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "versions", label: "Versions" },
];

export default function RegularizationPolicyDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("ATTENDANCE.POLICY_MANAGE");

  const [tab, setTab] = useState<TabKey>("overview");
  const [policy, setPolicy] = useState<RegularizationPolicy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<RegularizationPolicyFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<RegularizationPolicyFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);
  // Rules edited alongside the name on the Overview tab; saved into the draft version.
  const [editRules, setEditRules] = useState<RegularizationPolicyVersionFormValues | null>(null);
  const [editRuleErrors, setEditRuleErrors] = useState<RegularizationPolicyVersionFormErrors>({});
  const [startingEdit, setStartingEdit] = useState(false);
  // Snapshot of the rules when Edit opened, so Save can tell whether they were touched.
  const [editBaseline, setEditBaseline] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [statusChanging, setStatusChanging] = useState(false);

  const [versions, setVersions] = useState<RegularizationPolicyVersion[] | null>(null);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [creatingDraft, setCreatingDraft] = useState(false);

  const [draftValues, setDraftValues] =
    useState<RegularizationPolicyVersionFormValues | null>(null);
  const [draftErrors, setDraftErrors] = useState<RegularizationPolicyVersionFormErrors>({});
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
      const data = await apiClient.get<RegularizationPolicy>(
        `/regularization-policies/${params.id}`,
      );
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
      const data = await apiClient.get<RegularizationPolicyVersion[]>(
        `/regularization-policies/${params.id}/versions`,
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
    if (tab === "versions" && versions === null) void loadVersions();
  }, [tab, versions, loadVersions]);

  /** Edit opens the name and every rule at once. The rules start from the open draft, else a copy
   * of the published version, else the defaults — so there is no separate "create draft" step. */
  async function startEditing() {
    if (!policy) return;
    setStartingEdit(true);
    try {
      const loaded = versions ?? (await loadVersions());
      if (!loaded) return;
      const openDraft = loaded.find((v) => v.status === "DRAFT") ?? null;
      const published =
        loaded.find((v) => v.status === "PUBLISHED" && v.effective_to === null) ?? null;
      const source = openDraft ?? published;
      const rules = source
        ? regularizationPolicyVersionToFormValues(source)
        : EMPTY_REGULARIZATION_POLICY_VERSION_FORM_VALUES;
      const initial = openDraft ? rules : { ...rules, effectiveFrom: "" };
      setEditRules(initial);
      setEditBaseline(JSON.stringify(initial));
      setEditRuleErrors({});
      setFormValues({ name: policy.name });
      setFormErrors({});
      setStaleMessage(null);
      setEditing(true);
    } finally {
      setStartingEdit(false);
    }
  }

  function cancelEditing() {
    setEditing(false);
    setFormValues(null);
    setEditRules(null);
    setEditBaseline(null);
    setFormErrors({});
    setEditRuleErrors({});
    setStaleMessage(null);
  }

  async function handleSave() {
    if (!policy || !formValues || !editRules) return;
    const clientErrors = validateRegularizationPolicyForm(formValues);
    const rulesChanged = JSON.stringify(editRules) !== editBaseline;
    const ruleErrors = rulesChanged ? validateRegularizationPolicyVersionForm(editRules) : {};
    if (Object.keys(clientErrors).length > 0 || Object.keys(ruleErrors).length > 0) {
      setFormErrors(clientErrors);
      setEditRuleErrors(ruleErrors);
      toast({ title: "Fix the highlighted fields", variant: "danger" });
      return;
    }
    setSaving(true);
    setFormErrors({});
    setEditRuleErrors({});
    setStaleMessage(null);
    try {
      const patch = buildRegularizationPolicyUpdatePatch(formValues, policy);
      if (Object.keys(patch).length > 0) {
        const updated = await apiClient.patch<RegularizationPolicy>(
          `/regularization-policies/${policy.id}`,
          patch,
          { ifMatch: String(policy.version) },
        );
        setPolicy(updated);
      }

      if (!rulesChanged) {
        setEditing(false);
        setFormValues(null);
        setEditRules(null);
        setEditBaseline(null);
        toast(
          Object.keys(patch).length > 0
            ? { title: "Policy saved", variant: "success" }
            : { title: "No changes to save", variant: "default" },
        );
        return;
      }

      const payload = buildRegularizationPolicyVersionPayload(editRules);
      let savedDraft: RegularizationPolicyVersion;
      if (draft) {
        savedDraft = await apiClient.patch<RegularizationPolicyVersion>(
          `/regularization-policies/${params.id}/versions/${draft.id}`,
          payload,
          { ifMatch: String(draft.version) },
        );
      } else {
        savedDraft = await apiClient.post<RegularizationPolicyVersion>(
          `/regularization-policies/${params.id}/versions`,
          payload,
        );
      }
      setVersions((prev) => {
        const rest = (prev ?? []).filter((v) => v.id !== savedDraft.id);
        return [...rest, savedDraft];
      });
      setDraftValues(regularizationPolicyVersionToFormValues(savedDraft));
      setEditing(false);
      setFormValues(null);
      setEditRules(null);
      setEditBaseline(null);
      toast({ title: "Saved as a draft — publish it from the Versions tab", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("This policy was changed by someone else.");
          return;
        }
        if (err.status === 422) {
          setFormErrors({ name: getFieldError(err.details, "name") });
          setEditRuleErrors(mapRegularizationPolicyVersionApiErrors(err.details));
          return;
        }
        if (err.status === 403) {
          setError(err);
          setEditing(false);
          return;
        }
      }
      toast({
        title: "Could not save policy",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatest() {
    const [latest] = await Promise.all([loadPolicy(), loadVersions()]);
    if (latest) {
      setEditing(false);
      setFormValues(null);
      setEditRules(null);
      setDraftValues(null);
      setStaleMessage(null);
      toast({ title: "Reloaded", variant: "success" });
    }
  }

  async function handleToggleStatus() {
    if (!policy) return;
    setStatusChanging(true);
    try {
      const updated = await apiClient.patch<RegularizationPolicy>(
        `/regularization-policies/${policy.id}`,
        { is_active: !policy.is_active },
        { ifMatch: String(policy.version) },
      );
      setPolicy(updated);
      toast({
        title: updated.is_active ? "Policy reactivated" : "Policy deactivated",
        variant: "success",
      });
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
    setDraftValues(regularizationPolicyVersionToFormValues(draft));
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
      await apiClient.post(`/regularization-policies/${params.id}/versions`, {});
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

  async function handleSaveDraft(): Promise<boolean> {
    if (!draft || !draftValues) return false;
    const clientErrors = validateRegularizationPolicyVersionForm(draftValues);
    if (Object.keys(clientErrors).length > 0) {
      setDraftErrors(clientErrors);
      toast({ title: "Fix the highlighted fields", variant: "danger" });
      return false;
    }
    setSavingDraft(true);
    setDraftErrors({});
    setDraftStaleMessage(null);
    try {
      const payload = buildRegularizationPolicyVersionPayload(draftValues);
      const updated = await apiClient.patch<RegularizationPolicyVersion>(
        `/regularization-policies/${params.id}/versions/${draft.id}`,
        payload,
        { ifMatch: String(draft.version) },
      );
      setVersions((prev) => (prev ? prev.map((v) => (v.id === updated.id ? updated : v)) : prev));
      setDraftValues(regularizationPolicyVersionToFormValues(updated));
      toast({ title: "Draft saved", variant: "success" });
      return true;
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setDraftStaleMessage("This draft was changed by someone else.");
          return false;
        }
        if (err.status === 422) {
          setDraftErrors(mapRegularizationPolicyVersionApiErrors(err.details));
          return false;
        }
      }
      toast({
        title: "Could not save draft",
        description: describeApiError(err),
        variant: "danger",
      });
      return false;
    } finally {
      setSavingDraft(false);
    }
  }

  /** Publish acts on the saved draft, so unsaved edits are saved first; a failed save stops here. */
  async function handlePublishClick() {
    if (!draft || !draftValues) return;
    const hasUnsavedEdits = JSON.stringify(draftValues) !== JSON.stringify(regularizationPolicyVersionToFormValues(draft));
    if (hasUnsavedEdits && !(await handleSaveDraft())) return;
    setPublishDialogOpen(true);
  }

  async function reloadDraftLatest() {
    const latest = await loadVersions();
    if (latest) {
      setDraftStaleMessage(null);
      const latestDraft = latest.find((v) => v.status === "DRAFT") ?? null;
      setDraftValues(latestDraft ? regularizationPolicyVersionToFormValues(latestDraft) : null);
      toast({ title: "Reloaded", variant: "success" });
    }
  }

  async function handleDiscardDraft() {
    if (!draft) return;
    setDiscarding(true);
    try {
      await apiClient.delete(`/regularization-policies/${params.id}/versions/${draft.id}`, {
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
      <PageHeader
        backHref="/app/regularization-policies"
        backLabel="Regularization Policies"
        title={policy?.name ?? "Regularization Policy"}
        description="Edit the name and all regularization rules together; publish the saved draft from the Versions tab."
        badge={
          policy ? (
            <Badge variant={policy.is_active ? "secondary" : "outline"}>
              {policy.is_active ? "Active" : "Inactive"}
            </Badge>
          ) : undefined
        }
        actions={
          canManage && policy && !editing && tab === "overview" ? (
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)}>
                {policy.is_active ? "Deactivate" : "Reactivate"}
              </Button>
              <Button type="button" onClick={() => void startEditing()} disabled={startingEdit}>
                {startingEdit ? "Loading…" : "Edit"}
              </Button>
            </div>
          ) : null
        }
      />

      {loading ? (
        <Card>
          <CardContent>
            <LoadingState label="Loading policy…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent>
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
                className={cn(
                  "shrink-0 border-b-2 px-3.5 py-2.5 text-sm font-medium transition-colors duration-motion-instant focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  tab === item.key
                    ? "border-primary text-primary"
                    : "border-transparent text-foreground-secondary hover:border-border-strong hover:text-foreground",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>

          {tab === "overview" ? (
            <Card>
              <CardContent>
                {staleMessage ? (
                  <ConcurrencyConflictBanner
                    message={staleMessage}
                    onReload={() => void reloadLatest()}
                    onCancel={cancelEditing}
                  />
                ) : null}
                {editing && formValues && editRules ? (
                  <div className="space-y-6">
                    <RegularizationPolicyForm
                      values={formValues}
                      errors={formErrors}
                      onChange={setFormValues}
                    />
                    <RegularizationPolicyVersionForm
                      values={editRules}
                      errors={editRuleErrors}
                      onChange={setEditRules}
                    />
                    <div className="flex flex-wrap gap-2 border-t border-border pt-4">
                      <Button type="button" onClick={() => void handleSave()} disabled={saving}>
                        {saving ? "Saving…" : "Save"}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={cancelEditing}
                        disabled={saving}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div>
                        <dt className="text-xs font-medium text-foreground-muted">Policy name</dt>
                        <dd className="mt-0.5 text-sm font-medium text-foreground">
                          {policy.name}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium text-foreground-muted">Policy code</dt>
                        <dd className="mt-0.5 font-mono text-sm text-foreground">
                          {policy.code ?? "—"}
                        </dd>
                      </div>
                    </dl>
                    <p className="text-xs text-foreground-muted">
                      Click Edit to set the name and all rules. Publish and history are on the{" "}
                      <button
                        type="button"
                        className="font-medium text-primary hover:underline"
                        onClick={() => setTab("versions")}
                      >
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
                  <CardContent>
                    <LoadingState label="Loading versions…" />
                  </CardContent>
                </Card>
              ) : null}

              {versions !== null ? (
                <>
                  <Card>
                    <CardHeader>
                      <CardTitle>Currently published</CardTitle>
                    </CardHeader>
                    <CardContent>
                      {currentPublished ? (
                        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                          <div>
                            <dt className="text-xs font-medium text-foreground-muted">
                              Effective from
                            </dt>
                            <dd className="mt-0.5 text-sm font-medium tabular-nums text-foreground">
                              <CompanyDate value={currentPublished.effective_from} />
                            </dd>
                          </div>
                          <div>
                            <dt className="text-xs font-medium text-foreground-muted">
                              Approval chain
                            </dt>
                            <dd className="mt-0.5 text-sm font-medium text-foreground">
                              {currentPublished.approval_chain.replaceAll("_", " ")}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-xs font-medium text-foreground-muted">
                              Allowed types
                            </dt>
                            <dd className="mt-0.5 text-sm font-medium tabular-nums text-foreground">
                              {currentPublished.allowed_types.length} configured
                            </dd>
                          </div>
                        </dl>
                      ) : (
                        <p className="text-sm text-foreground-muted">No published version yet.</p>
                      )}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader className="flex-row items-center justify-between space-y-0">
                      <CardTitle>Draft</CardTitle>
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
                    </CardHeader>
                    <CardContent className="space-y-4">
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
                          <RegularizationPolicyVersionForm
                            values={draftValues}
                            errors={draftErrors}
                            onChange={setDraftValues}
                          />
                          <div className="flex flex-wrap gap-2 border-t border-border pt-4">
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
                                  onClick={() => void handlePublishClick()}
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
                    <TableContainer>
                      <TableToolbar>
                        <h3 className="text-sm font-semibold text-foreground">History</h3>
                      </TableToolbar>
                      <Table>
                        <TableHeader>
                          <TableRow className="hover:bg-transparent">
                            <TableHead>Effective period</TableHead>
                            <TableHead>Summary</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {historical.map((version) => (
                            <TableRow key={version.id}>
                              <TableCell className="tabular-nums text-foreground-secondary">
                                <CompanyDate value={version.effective_from} /> –{" "}
                                {version.effective_to ? (
                                  <CompanyDate value={version.effective_to} />
                                ) : (
                                  "open"
                                )}
                              </TableCell>
                              <TableCell className="font-medium text-foreground">
                                {version.approval_chain.replaceAll("_", " ")} —{" "}
                                {version.allowed_types.length} allowed types
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  ) : null}
                </>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}

      <Dialog
        open={confirmOpen}
        onOpenChange={(open) => (!statusChanging ? setConfirmOpen(open) : null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {policy?.is_active ? "Deactivate policy?" : "Reactivate policy?"}
            </DialogTitle>
            <DialogDescription>
              {policy?.is_active
                ? "This policy will no longer be assignable to a new scope. Existing assignments are unaffected."
                : "This policy becomes assignable again."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={statusChanging}
            >
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
          versionsPath={`/regularization-policies/${params.id}/versions`}
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
