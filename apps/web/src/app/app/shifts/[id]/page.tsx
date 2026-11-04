"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ConcurrencyConflictBanner } from "@/components/employee/concurrency-conflict-banner";
import { ShiftDeleteDialog } from "@/components/shift/shift-delete-dialog";
import { ShiftForm } from "@/components/shift/shift-form";
import { ShiftPublishDialog } from "@/components/shift/shift-publish-dialog";
import { ShiftVersionForm } from "@/components/shift/shift-version-form";
import { CompanyDate } from "@/components/common/company-date";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { PaginationControls } from "@/components/common/pagination-controls";
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
import {
  ApiError,
  describeApiError,
  describeLifecycleError,
  getFieldError,
} from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { Shift, ShiftVersion } from "@/lib/shift/types";
import {
  buildUpdatePatch,
  shiftToFormValues,
  validateShiftForm,
  type ShiftFormErrors,
  type ShiftFormValues,
} from "@/lib/shift/validate-shift";
import {
  EMPTY_SHIFT_VERSION_FORM_VALUES,
  buildShiftVersionPatch,
  mapShiftVersionApiErrors,
  shiftVersionToFormValues,
  validateShiftVersionForm,
  type ShiftVersionFormErrors,
  type ShiftVersionFormValues,
} from "@/lib/shift/validate-shift-version";
import type { WeeklyOffPattern } from "@/lib/weekly-off-pattern/types";

type TabKey = "overview" | "versions";
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "versions", label: "Versions" },
];

function formatVersionTiming(version: ShiftVersion): string {
  if (version.shift_type === "FIXED") {
    return `${version.start_time ?? "—"}–${version.end_time ?? "—"}${version.is_cross_midnight ? " (crosses midnight)" : ""}`;
  }
  if (version.shift_type === "FLEXIBLE") {
    return `Flexible window ${version.window_start ?? "—"}–${version.window_end ?? "—"}`;
  }
  if (version.shift_type === "SPLIT") {
    return version.duty_blocks
      .slice()
      .sort((a, b) => a.sequence - b.sequence)
      .map((block) => `${block.start_time}–${block.end_time}`)
      .join(" + ");
  }
  return "Not yet configured";
}

export default function ShiftDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("ORG.SHIFT.MANAGE");

  const [tab, setTab] = useState<TabKey>("overview");

  const [shift, setShift] = useState<Shift | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<ShiftFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<ShiftFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);
  // Schedule edited alongside the name on the Overview tab; saved into the draft version.
  const [editSchedule, setEditSchedule] = useState<ShiftVersionFormValues | null>(null);
  const [editScheduleErrors, setEditScheduleErrors] = useState<ShiftVersionFormErrors>({});
  const [startingEdit, setStartingEdit] = useState(false);
  // Snapshot of the rules when Edit opened, so Save can tell whether they were touched.
  const [editBaseline, setEditBaseline] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const router = useRouter();
  const [statusChanging, setStatusChanging] = useState(false);

  // --- Versions tab state ---
  const [versions, setVersions] = useState<ShiftVersion[] | null>(null);
  const [latestVersions, setLatestVersions] = useState<ShiftVersion[] | null>(
    null,
  );
  const [versionsPagination, setVersionsPagination] =
    useState<PaginationMeta | null>(null);
  const [versionsPage, setVersionsPage] = useState(1);
  const [weeklyOffPatterns, setWeeklyOffPatterns] = useState<
    WeeklyOffPattern[]
  >([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [creatingDraft, setCreatingDraft] = useState(false);

  const [draftValues, setDraftValues] = useState<ShiftVersionFormValues | null>(
    null,
  );
  const [draftErrors, setDraftErrors] = useState<ShiftVersionFormErrors>({});
  const [savingDraft, setSavingDraft] = useState(false);
  const [draftStaleMessage, setDraftStaleMessage] = useState<string | null>(
    null,
  );

  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [publishDialogOpen, setPublishDialogOpen] = useState(false);

  // `latestVersions` is always page 1 (newest-first) — the open DRAFT and the currently
  // PUBLISHED version, if either exists, are always more recent than every superseded
  // historical row, so they're guaranteed to land on page 1 regardless of how many versions
  // this shift has accumulated (API-01 §6). `versions` is whichever page the "History" list
  // below is currently browsing — never used to derive these two, so paging through history
  // can't make the draft/current-published sections flicker or disappear.
  const draft = latestVersions?.find((v) => v.status === "DRAFT") ?? null;
  const currentPublished =
    latestVersions?.find(
      (v) => v.status === "PUBLISHED" && v.effective_to === null,
    ) ?? null;
  const historical =
    versions
      ?.filter((v) => v.id !== draft?.id && v.id !== currentPublished?.id)
      .sort((a, b) =>
        (b.effective_from ?? "").localeCompare(a.effective_from ?? ""),
      ) ?? [];

  const loadShift = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<Shift>(`/shifts/${params.id}`);
      setShift(data);
      return data;
    } catch (err) {
      setShift(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({
              status: 0,
              code: "UNKNOWN_ERROR",
              message: "Something went wrong.",
            }),
      );
      return null;
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  const loadVersions = useCallback(
    async (targetPage: number) => {
      setVersionsLoading(true);
      try {
        const [versionResult, patternData] = await Promise.all([
          apiClient.getList<ShiftVersion>(`/shifts/${params.id}/versions`, {
            page: targetPage,
          }),
          apiClient.get<WeeklyOffPattern[]>("/weekly-off-patterns"),
        ]);
        setVersions(versionResult.data);
        setVersionsPagination(versionResult.pagination);
        if (targetPage === 1) setLatestVersions(versionResult.data);
        setWeeklyOffPatterns(patternData);
        return versionResult.data;
      } catch (err) {
        toast({
          title: "Could not load shift versions",
          description: describeApiError(err),
          variant: "danger",
        });
        return null;
      } finally {
        setVersionsLoading(false);
      }
    },
    [params.id, toast],
  );

  useEffect(() => {
    void loadShift();
  }, [loadShift]);

  useEffect(() => {
    if (tab !== "versions") return;
    // Fires on first opening the tab, and again whenever the "History" pager below changes
    // `versionsPage` — the draft/current-published sections stay pinned to `latestVersions`
    // (always page 1) regardless of which history page this loads.
    void loadVersions(versionsPage);
    // `versions`/`loadVersions` intentionally excluded — including them would refire this on
    // every load, not just on tab-open/page-change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, versionsPage]);

  // --- Identity (Overview) editing ---

  /** Edit opens the name and the whole schedule at once. The schedule starts from the open draft,
   * else a copy of the published version, else blank — so there is no separate "create draft"
   * step. */
  async function startEditing() {
    if (!shift) return;
    setStartingEdit(true);
    try {
      setVersionsPage(1);
      const loaded = await loadVersions(1);
      if (!loaded) return;
      const openDraft = loaded.find((v) => v.status === "DRAFT") ?? null;
      const published =
        loaded.find((v) => v.status === "PUBLISHED" && v.effective_to === null) ?? null;
      const source = openDraft ?? published;
      const schedule = source
        ? shiftVersionToFormValues(source)
        : EMPTY_SHIFT_VERSION_FORM_VALUES;
      const initial = openDraft ? schedule : { ...schedule, effectiveFrom: "" };
      setEditSchedule(initial);
      setEditBaseline(JSON.stringify(initial));
      setEditScheduleErrors({});
      setFormValues(shiftToFormValues(shift));
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
    setEditSchedule(null);
    setEditBaseline(null);
    setFormErrors({});
    setEditScheduleErrors({});
    setStaleMessage(null);
  }

  async function handleSave(thenPublish = false) {
    if (!shift || !formValues || !editSchedule) return;

    const clientErrors = validateShiftForm(formValues);
    const rulesChanged = JSON.stringify(editSchedule) !== editBaseline;
    const scheduleErrors = rulesChanged ? validateShiftVersionForm(editSchedule) : {};
    if (Object.keys(clientErrors).length > 0 || Object.keys(scheduleErrors).length > 0) {
      setFormErrors(clientErrors);
      setEditScheduleErrors(scheduleErrors);
      toast({ title: "Fix the highlighted fields", variant: "danger" });
      return;
    }

    setSaving(true);
    setFormErrors({});
    setEditScheduleErrors({});
    setStaleMessage(null);
    try {
      const patch = buildUpdatePatch(formValues, shift);
      if (Object.keys(patch).length > 0) {
        const updated = await apiClient.patch<Shift>(`/shifts/${shift.id}`, patch, {
          ifMatch: String(shift.version),
        });
        setShift(updated);
      }

      if (!rulesChanged) {
        if (thenPublish && draft) setPublishDialogOpen(true);
        setEditing(false);
        setFormValues(null);
        setEditSchedule(null);
        setEditBaseline(null);
        toast(
          Object.keys(patch).length > 0
            ? { title: "Shift saved", variant: "success" }
            : { title: "No changes to save", variant: "default" },
        );
        return;
      }

      // No open draft yet: create an empty one, then fill it with the same PATCH an existing
      // draft gets (the draft builder diffs breaks/duty blocks against the row it patches).
      const target =
        draft ?? (await apiClient.post<ShiftVersion>(`/shifts/${params.id}/versions`, {}));
      const savedDraft = await apiClient.patch<ShiftVersion>(
        `/shifts/${params.id}/versions/${target.id}`,
        buildShiftVersionPatch(editSchedule, target),
        { ifMatch: String(target.version) },
      );
      const upsert = (prev: ShiftVersion[] | null) =>
        [...(prev ?? []).filter((v) => v.id !== savedDraft.id), savedDraft];
      setVersions(upsert);
      setLatestVersions(upsert);
      setDraftValues(shiftVersionToFormValues(savedDraft));
      setEditing(false);
      setFormValues(null);
      setEditSchedule(null);
      setEditBaseline(null);
      if (thenPublish) {
        setPublishDialogOpen(true);
      } else {
        toast({
          title: "Saved as a draft — publish it from the Versions tab",
          variant: "success",
        });
      }
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("This shift was changed by someone else.");
          return;
        }
        if (err.status === 422) {
          setFormErrors({ name: getFieldError(err.details, "name") });
          setEditScheduleErrors(mapShiftVersionApiErrors(err.details));
          return;
        }
        if (err.status === 403) {
          setError(err);
          setEditing(false);
          return;
        }
      }
      toast({
        title: "Could not save shift",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatest() {
    setVersionsPage(1);
    const [latest] = await Promise.all([loadShift(), loadVersions(1)]);
    if (latest) {
      setEditing(false);
      setFormValues(null);
      setEditSchedule(null);
      setDraftValues(null);
      setStaleMessage(null);
      toast({ title: "Reloaded", variant: "success" });
    }
  }

  async function handleToggleStatus() {
    if (!shift) return;
    setStatusChanging(true);
    try {
      if (shift.is_active) {
        const updated = await apiClient.delete<Shift>(`/shifts/${shift.id}`, {
          ifMatch: String(shift.version),
        });
        setShift(updated);
        toast({ title: "Shift deactivated", variant: "success" });
      } else {
        const updated = await apiClient.patch<Shift>(
          `/shifts/${shift.id}`,
          { is_active: true },
          { ifMatch: String(shift.version) },
        );
        setShift(updated);
        toast({ title: "Shift reactivated", variant: "success" });
      }
      setConfirmOpen(false);
    } catch (err) {
      toast({
        title: "Could not update shift status",
        description: describeLifecycleError(err),
        variant: "danger",
      });
    } finally {
      setStatusChanging(false);
    }
  }

  // --- Versions tab actions ---

  function startEditingDraft() {
    if (!draft) return;
    setDraftValues(shiftVersionToFormValues(draft));
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
      await apiClient.post(`/shifts/${params.id}/versions`, {});
      toast({ title: "Draft created", variant: "success" });
      setVersionsPage(1);
      await loadVersions(1);
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
    const clientErrors = validateShiftVersionForm(draftValues);
    if (Object.keys(clientErrors).length > 0) {
      setDraftErrors(clientErrors);
      toast({ title: "Fix the highlighted fields", variant: "danger" });
      return false;
    }

    setSavingDraft(true);
    setDraftErrors({});
    setDraftStaleMessage(null);
    try {
      const patch = buildShiftVersionPatch(draftValues, draft);
      const updated = await apiClient.patch<ShiftVersion>(
        `/shifts/${params.id}/versions/${draft.id}`,
        patch,
        { ifMatch: String(draft.version) },
      );
      setVersions((prev) =>
        prev ? prev.map((v) => (v.id === updated.id ? updated : v)) : prev,
      );
      setLatestVersions((prev) =>
        prev ? prev.map((v) => (v.id === updated.id ? updated : v)) : prev,
      );
      setDraftValues(shiftVersionToFormValues(updated));
      toast({ title: "Draft saved", variant: "success" });
      return true;
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setDraftStaleMessage("This draft was changed by someone else.");
          return false;
        }
        if (err.status === 422) {
          setDraftErrors(mapShiftVersionApiErrors(err.details));
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
    const hasUnsavedEdits = JSON.stringify(draftValues) !== JSON.stringify(shiftVersionToFormValues(draft));
    if (hasUnsavedEdits && !(await handleSaveDraft())) return;
    setPublishDialogOpen(true);
  }

  async function reloadDraftLatest() {
    setVersionsPage(1);
    const latest = await loadVersions(1);
    if (latest) {
      setDraftStaleMessage(null);
      const latestDraft = latest.find((v) => v.status === "DRAFT") ?? null;
      setDraftValues(
        latestDraft ? shiftVersionToFormValues(latestDraft) : null,
      );
      toast({ title: "Reloaded", variant: "success" });
    }
  }

  async function handleDiscardDraft() {
    if (!draft) return;
    setDiscarding(true);
    try {
      await apiClient.delete(`/shifts/${params.id}/versions/${draft.id}`, {
        ifMatch: String(draft.version),
      });
      setDiscardConfirmOpen(false);
      setDraftValues(null);
      toast({ title: "Draft discarded", variant: "success" });
      setVersionsPage(1);
      await loadVersions(1);
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

  function handlePublished(_updated: ShiftVersion) {
    // The now-superseded published version's effective_to is set server-side — refetch the
    // whole list rather than approximating it here.
    setDraftValues(null);
    toast({ title: "Schedule published", variant: "success" });
    setVersionsPage(1);
    void loadVersions(1);
    void loadShift();
  }

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/app/shifts"
          className="text-sm text-foreground-secondary hover:underline"
        >
          ← Shifts
        </Link>
      </div>

      <PageHeader
        title={shift?.name ?? "Shift"}
        description="Edit the name and the whole schedule together, then save and publish in one go. Drafts and past versions are on the Versions tab."
        actions={
          canManage && shift && !editing && tab === "overview" ? (
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setConfirmOpen(true)}
              >
                {shift.is_active ? "Deactivate" : "Reactivate"}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => setDeleteOpen(true)}
              >
                Delete
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
          <CardContent className="pt-6">
            <LoadingState label="Loading shift…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this shift."
                  : error.status === 404
                    ? "This shift could not be found."
                    : error.message
              }
              onRetry={
                error.status === 404 ? undefined : () => void loadShift()
              }
            />
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && shift ? (
        <>
          <div
            className="flex gap-1 overflow-x-auto border-b border-border"
            role="tablist"
          >
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

                {editing && formValues && editSchedule ? (
                  <div className="space-y-6">
                    <ShiftForm
                      values={formValues}
                      errors={formErrors}
                      onChange={setFormValues}
                    />
                    <ShiftVersionForm
                      values={editSchedule}
                      errors={editScheduleErrors}
                      onChange={setEditSchedule}
                      weeklyOffPatterns={weeklyOffPatterns}
                    />
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        onClick={() => void handleSave(true)}
                        disabled={saving}
                      >
                        Save &amp; publish…
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => void handleSave()}
                        disabled={saving}
                      >
                        {saving ? "Saving…" : "Save as draft"}
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
                    <Badge variant={shift.is_active ? "secondary" : "outline"}>
                      {shift.is_active ? "Active" : "Inactive"}
                    </Badge>
                    <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div>
                        <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                          Shift name
                        </dt>
                        <dd className="mt-0.5 text-sm text-foreground">
                          {shift.name}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                          Shift code
                        </dt>
                        <dd className="mt-0.5 text-sm text-foreground">
                          {shift.code ?? "—"}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                          Current schedule
                        </dt>
                        <dd className="mt-0.5 text-sm text-foreground">
                          {shift.current_version_id ? (
                            <Badge variant="secondary">Published</Badge>
                          ) : (
                            <span className="text-foreground-muted">
                              Not published yet
                            </span>
                          )}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                          Draft schedule
                        </dt>
                        <dd className="mt-0.5 text-sm text-foreground">
                          {shift.draft_version_id ? (
                            <Badge variant="outline">Draft in progress</Badge>
                          ) : (
                            <span className="text-foreground-muted">None</span>
                          )}
                        </dd>
                      </div>
                    </dl>
                    <p className="text-xs text-foreground-muted">
                      Click Edit to set the name and the full schedule. Publish and history are on the{" "}
                      <button
                        type="button"
                        className="underline"
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
                  <CardContent className="pt-6">
                    <LoadingState label="Loading versions…" />
                  </CardContent>
                </Card>
              ) : null}

              {versions !== null ? (
                <>
                  <Card>
                    <CardContent className="space-y-4 pt-6">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-medium text-foreground">
                          Currently published
                        </h3>
                      </div>
                      {currentPublished ? (
                        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                          <div>
                            <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                              Type
                            </dt>
                            <dd className="mt-0.5 text-sm text-foreground">
                              {currentPublished.shift_type}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                              Timing
                            </dt>
                            <dd className="mt-0.5 text-sm text-foreground">
                              {formatVersionTiming(currentPublished)}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                              Effective from
                            </dt>
                            <dd className="mt-0.5 text-sm text-foreground">
                              <CompanyDate
                                value={currentPublished.effective_from}
                              />
                            </dd>
                          </div>
                        </dl>
                      ) : (
                        <p className="text-sm text-foreground-muted">
                          No published schedule yet — this shift cannot be
                          assigned to employees until a draft is published.
                        </p>
                      )}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardContent className="space-y-4 pt-6">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-medium text-foreground">
                          Draft
                        </h3>
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
                          No open draft. Start one to change this shift&apos;s
                          schedule.
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
                          <ShiftVersionForm
                            values={draftValues}
                            errors={draftErrors}
                            onChange={setDraftValues}
                            weeklyOffPatterns={weeklyOffPatterns}
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
                    <Card>
                      <CardContent className="pt-6">
                        <h3 className="text-sm font-medium text-foreground">
                          History
                        </h3>
                        <ul className="mt-3 divide-y divide-border">
                          {historical.map((version) => (
                            <li
                              key={version.id}
                              className="py-3 first:pt-0 last:pb-0"
                            >
                              <p className="text-sm font-medium text-foreground">
                                {version.shift_type} —{" "}
                                {formatVersionTiming(version)}
                              </p>
                              <p className="mt-0.5 text-xs text-foreground-muted">
                                <CompanyDate value={version.effective_from} /> –{" "}
                                {version.effective_to ? (
                                  <CompanyDate value={version.effective_to} />
                                ) : (
                                  "open"
                                )}
                              </p>
                            </li>
                          ))}
                        </ul>
                        {versionsPagination ? (
                          <PaginationControls
                            pagination={versionsPagination}
                            onPageChange={setVersionsPage}
                            disabled={versionsLoading}
                          />
                        ) : null}
                      </CardContent>
                    </Card>
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
              {shift?.is_active ? "Deactivate shift?" : "Reactivate shift?"}
            </DialogTitle>
            <DialogDescription>
              {shift?.is_active
                ? "This shift will no longer be available for new activity. You can reactivate it later."
                : "This shift will become available for use again."}
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
              variant={shift?.is_active ? "destructive" : "default"}
              onClick={() => void handleToggleStatus()}
              disabled={statusChanging}
            >
              {statusChanging
                ? "Saving…"
                : shift?.is_active
                  ? "Deactivate"
                  : "Reactivate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={discardConfirmOpen}
        onOpenChange={(open) =>
          !discarding ? setDiscardConfirmOpen(open) : null
        }
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Discard this draft?</DialogTitle>
            <DialogDescription>
              This removes the unpublished changes. The currently published
              schedule (if any) is unaffected.
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

      {shift ? (
        <ShiftDeleteDialog
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
          shift={shift}
          onDeleted={() => {
            toast({ title: "Shift deleted", variant: "success" });
            router.push("/app/shifts");
          }}
          onStale={() => {
            setStaleMessage("This shift was changed by someone else.");
            void loadShift();
          }}
        />
      ) : null}

      {draft ? (
        <ShiftPublishDialog
          open={publishDialogOpen}
          onOpenChange={setPublishDialogOpen}
          shiftId={params.id}
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
