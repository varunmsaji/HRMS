"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AttendancePolicyForm } from "@/components/attendance-policy/attendance-policy-form";
import { AttendancePolicySummary } from "@/components/attendance-policy/attendance-policy-summary";
import { AttendancePolicyVersionForm } from "@/components/attendance-policy/attendance-policy-version-form";
import { CompanyDate } from "@/components/common/company-date";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { ConcurrencyConflictBanner } from "@/components/employee/concurrency-conflict-banner";
import {
  PublishAssignDialog,
  type PublishChoice,
} from "@/components/policy-assignment/publish-assign-dialog";
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
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { AttendancePolicy, AttendancePolicyVersion } from "@/lib/attendance-policy/types";
import {
  attendancePolicyVersionToFormValues,
  buildAttendancePolicyUpdatePatch,
  buildAttendancePolicyVersionPayload,
  EMPTY_ATTENDANCE_POLICY_VERSION_FORM_VALUES,
  mapAttendancePolicyVersionApiErrors,
  validateAttendancePolicyForm,
  validateAttendancePolicyForPublish,
  validateAttendancePolicyVersionForm,
  type AttendancePolicyFormErrors,
  type AttendancePolicyVersionFormErrors,
  type AttendancePolicyVersionFormValues,
} from "@/lib/attendance-policy/validate-attendance-policy";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import { cn } from "@/lib/utils";

type TabKey = "rules" | "history";
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "rules", label: "Rules" },
  { key: "history", label: "History" },
];

function nextDay(date: string): string {
  const next = new Date(`${date}T00:00:00Z`);
  next.setUTCDate(next.getUTCDate() + 1);
  return next.toISOString().slice(0, 10);
}

function toApiError(err: unknown): ApiError {
  return err instanceof ApiError
    ? err
    : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." });
}

export default function AttendancePolicyDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const { can } = usePermissions();
  const { user } = useAuth();
  const canManage = can("ATTENDANCE.POLICY_MANAGE");
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");

  const [tab, setTab] = useState<TabKey>("rules");
  const [policy, setPolicy] = useState<AttendancePolicy | null>(null);
  const [versions, setVersions] = useState<AttendancePolicyVersion[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [shiftTypes, setShiftTypes] = useState<string[] | null>(null);

  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [rules, setRules] = useState<AttendancePolicyVersionFormValues | null>(null);
  const [nameErrors, setNameErrors] = useState<AttendancePolicyFormErrors>({});
  const [ruleErrors, setRuleErrors] = useState<AttendancePolicyVersionFormErrors>({});
  const [staleMessage, setStaleMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [publishOpen, setPublishOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [statusChanging, setStatusChanging] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [discarding, setDiscarding] = useState(false);

  const load = useCallback(async () => {
    try {
      const [policyData, versionData] = await Promise.all([
        apiClient.get<AttendancePolicy>(`/attendance-policies/${params.id}`),
        apiClient.get<AttendancePolicyVersion[]>(`/attendance-policies/${params.id}/versions`),
      ]);
      setPolicy(policyData);
      setVersions(versionData);
      setError(null);
    } catch (err) {
      setError(toApiError(err));
    }
  }, [params.id]);

  useEffect(() => {
    void load();
    apiClient
      .get<{ shift_types_in_use: string[] }>("/attendance-policies/form-context")
      .then((context) => setShiftTypes(context.shift_types_in_use))
      .catch(() => setShiftTypes(null));
  }, [load]);

  const draft = versions?.find((v) => v.status === "DRAFT") ?? null;
  const current =
    versions?.find((v) => v.status === "PUBLISHED" && v.effective_to === null) ?? null;
  const published = (versions ?? [])
    .filter((v) => v.status === "PUBLISHED")
    .sort((a, b) => (b.effective_from ?? "").localeCompare(a.effective_from ?? ""));

  // The open version may not have started yet; the version in force today is what "live" means.
  const liveToday =
    published.find(
      (v) =>
        v.effective_from !== null &&
        v.effective_from <= today &&
        (v.effective_to === null || v.effective_to >= today),
    ) ?? null;
  const scheduled = current && current.id !== liveToday?.id ? current : null;

  function startEditing() {
    if (!policy) return;
    const source = draft ?? current;
    const values = source
      ? attendancePolicyVersionToFormValues(source)
      : EMPTY_ATTENDANCE_POLICY_VERSION_FORM_VALUES;
    setRules(draft ? values : { ...values, effectiveFrom: "" });
    setName(policy.name);
    setNameErrors({});
    setRuleErrors({});
    setStaleMessage(null);
    setEditing(true);
  }

  function stopEditing() {
    setEditing(false);
    setRules(null);
    setNameErrors({});
    setRuleErrors({});
    setStaleMessage(null);
  }

  /** Saves the name and rules into the draft, creating it if needed. Null means it failed and
   * the reason is already on screen. */
  async function saveRules(
    values: AttendancePolicyVersionFormValues,
  ): Promise<AttendancePolicyVersion | null> {
    if (!policy) return null;
    try {
      const patch = editing ? buildAttendancePolicyUpdatePatch({ name }, policy) : {};
      if (Object.keys(patch).length > 0) {
        setPolicy(
          await apiClient.patch<AttendancePolicy>(`/attendance-policies/${policy.id}`, patch, {
            ifMatch: String(policy.version),
          }),
        );
      }
      const payload = buildAttendancePolicyVersionPayload(values);
      return draft
        ? await apiClient.patch<AttendancePolicyVersion>(
            `/attendance-policies/${policy.id}/versions/${draft.id}`,
            payload,
            { ifMatch: String(draft.version) },
          )
        : await apiClient.post<AttendancePolicyVersion>(
            `/attendance-policies/${policy.id}/versions`,
            payload,
          );
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === "STALE_RESOURCE") {
        setPublishOpen(false);
        setStaleMessage("This policy was changed by someone else.");
      } else if (err instanceof ApiError && err.status === 422) {
        setPublishOpen(false);
        setNameErrors({ name: getFieldError(err.details, "name") });
        setRuleErrors(mapAttendancePolicyVersionApiErrors(err.details));
        toast({ title: "Fix the highlighted fields", variant: "danger" });
      } else {
        setPublishError(describeApiError(err));
        toast({ title: "Could not save", description: describeApiError(err), variant: "danger" });
      }
      return null;
    }
  }

  async function handleSaveDraft() {
    if (!rules) return;
    const nameCheck = validateAttendancePolicyForm({ name });
    const ruleCheck = validateAttendancePolicyVersionForm(rules);
    setNameErrors(nameCheck);
    setRuleErrors(ruleCheck);
    if (Object.keys(nameCheck).length > 0 || Object.keys(ruleCheck).length > 0) {
      toast({ title: "Fix the highlighted fields", variant: "danger" });
      return;
    }
    setSaving(true);
    const saved = await saveRules(rules);
    setSaving(false);
    if (!saved) return;
    toast({ title: "Draft saved. It isn't live until you publish it.", variant: "success" });
    stopEditing();
    await load();
  }

  function openPublish() {
    const values =
      rules ?? (draft ? attendancePolicyVersionToFormValues(draft) : null);
    if (!values) return;
    const nameCheck = editing ? validateAttendancePolicyForm({ name }) : {};
    const ruleCheck = validateAttendancePolicyForPublish(values);
    setNameErrors(nameCheck);
    setRuleErrors(ruleCheck);
    if (Object.keys(nameCheck).length > 0 || Object.keys(ruleCheck).length > 0) {
      if (!editing) startEditing();
      toast({ title: "Fix the highlighted fields", variant: "danger" });
      return;
    }
    setPublishError(null);
    setPublishOpen(true);
  }

  function initialPublishDate(): string {
    const fromDraft = rules?.effectiveFrom || draft?.effective_from;
    if (fromDraft) return fromDraft;
    if (current?.effective_from && current.effective_from >= today) {
      return nextDay(current.effective_from);
    }
    return today;
  }

  async function handlePublish(choice: PublishChoice) {
    if (!policy) return;
    const values = rules ?? (draft ? attendancePolicyVersionToFormValues(draft) : null);
    if (!values) return;
    setPublishing(true);
    setPublishError(null);
    try {
      const saved = await saveRules({ ...values, effectiveFrom: choice.effectiveFrom });
      if (!saved) return;
      await apiClient.post(
        `/attendance-policies/${policy.id}/versions/${saved.id}/publish`,
        {
          publish_reason: choice.reason || null,
          ...(current ? { expected_previous_version: current.version } : {}),
        },
        { ifMatch: String(saved.version) },
      );
      if (choice.assign) {
        try {
          await apiClient.post("/policy-assignments/batch", {
            scope_type: choice.assign.scopeType,
            scope_id: choice.assign.scopeId,
            effective_from: choice.effectiveFrom,
            reason: choice.reason || null,
            changes: [
              {
                policy_kind: "ATTENDANCE_POLICY",
                policy_id: policy.id,
                expected_version: choice.assign.expectedVersion,
              },
            ],
          });
        } catch (err) {
          toast({
            title: "Published, but not assigned",
            description: `${describeApiError(err)} Assign it from Policy Assignments.`,
            variant: "danger",
          });
          setPublishOpen(false);
          stopEditing();
          await load();
          return;
        }
      }
      toast({ title: "Policy published", variant: "success" });
      setPublishOpen(false);
      stopEditing();
      await load();
    } catch (err) {
      setPublishError(describeApiError(err));
      // The draft was saved; its version changed, so the next attempt must use the new one.
      await load();
    } finally {
      setPublishing(false);
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

  async function handleDiscardDraft() {
    if (!policy || !draft) return;
    setDiscarding(true);
    try {
      await apiClient.delete(`/attendance-policies/${policy.id}/versions/${draft.id}`, {
        ifMatch: String(draft.version),
      });
      setDiscardOpen(false);
      stopEditing();
      toast({ title: "Draft discarded", variant: "success" });
      await load();
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

  const loading = !error && (policy === null || versions === null);

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/attendance-policies"
        backLabel="Attendance Policies"
        title={policy?.name ?? "Attendance Policy"}
        badge={
          policy ? (
            <Badge variant={policy.is_active ? "secondary" : "outline"}>
              {policy.is_active ? "Active" : "Inactive"}
            </Badge>
          ) : undefined
        }
        actions={
          canManage && policy && !editing ? (
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)}>
                {policy.is_active ? "Deactivate" : "Reactivate"}
              </Button>
              <Button type="button" onClick={startEditing} disabled={versions === null}>
                {draft ? "Continue editing draft" : "Edit rules"}
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

      {error ? (
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
              onRetry={error.status === 404 ? undefined : () => void load()}
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

          {tab === "rules" && editing && rules ? (
            <Card>
              <CardContent className="space-y-6 pt-6">
                {staleMessage ? (
                  <ConcurrencyConflictBanner
                    message={staleMessage}
                    onReload={() => {
                      stopEditing();
                      void load();
                    }}
                    onCancel={stopEditing}
                  />
                ) : null}
                <AttendancePolicyForm
                  values={{ name }}
                  errors={nameErrors}
                  onChange={(values) => setName(values.name)}
                />
                <AttendancePolicyVersionForm
                  values={rules}
                  errors={ruleErrors}
                  onChange={setRules}
                  shiftTypesInUse={shiftTypes}
                />
                <div className="flex flex-wrap gap-2 border-t border-border pt-4">
                  <Button type="button" onClick={openPublish} disabled={saving}>
                    Save &amp; publish…
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => void handleSaveDraft()}
                    disabled={saving}
                  >
                    {saving ? "Saving…" : "Save as draft"}
                  </Button>
                  <Button type="button" variant="ghost" onClick={stopEditing} disabled={saving}>
                    Cancel
                  </Button>
                  {draft ? (
                    <Button
                      type="button"
                      variant="ghost"
                      className="ml-auto text-danger"
                      onClick={() => setDiscardOpen(true)}
                      disabled={saving}
                    >
                      Discard draft
                    </Button>
                  ) : null}
                </div>
              </CardContent>
            </Card>
          ) : null}

          {tab === "rules" && !editing ? (
            <div className="space-y-4">
              {draft && canManage ? (
                <Card>
                  <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6">
                    <p className="text-sm text-foreground">
                      There is an unpublished draft. Nobody follows it until it&apos;s published.
                    </p>
                    <div className="flex gap-2">
                      <Button type="button" size="sm" onClick={openPublish}>
                        Publish…
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => setDiscardOpen(true)}
                      >
                        Discard
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ) : null}
              <Card>
                <CardHeader>
                  <CardTitle>
                    {liveToday ? (
                      <>
                        Live rules since <CompanyDate value={liveToday.effective_from} />
                      </>
                    ) : (
                      "No live rules today"
                    )}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {liveToday ? (
                    <AttendancePolicySummary version={liveToday} />
                  ) : (
                    <p className="text-sm text-foreground-muted">
                      {scheduled
                        ? "These rules haven't started yet."
                        : draft
                          ? "Publish the draft to make these rules live."
                          : "Set the rules and publish them to make this policy usable."}
                    </p>
                  )}
                  {current ? (
                    <p className="text-xs text-foreground-muted">
                      Choose who follows this policy in{" "}
                      <Link
                        href="/app/policy-assignments"
                        className="font-medium text-primary hover:underline"
                      >
                        Policy Assignments
                      </Link>
                      .
                    </p>
                  ) : null}
                </CardContent>
              </Card>
              {scheduled ? (
                <Card>
                  <CardHeader>
                    <CardTitle>
                      New rules from <CompanyDate value={scheduled.effective_from} />
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <AttendancePolicySummary version={scheduled} />
                  </CardContent>
                </Card>
              ) : null}
            </div>
          ) : null}

          {tab === "history" ? (
            published.length === 0 ? (
              <Card>
                <CardContent className="pt-6">
                  <p className="text-sm text-foreground-muted">Nothing has been published yet.</p>
                </CardContent>
              </Card>
            ) : (
              <TableContainer>
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead>Effective period</TableHead>
                      <TableHead>Summary</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {published.map((version) => (
                      <TableRow key={version.id}>
                        <TableCell className="tabular-nums text-foreground-secondary">
                          <CompanyDate value={version.effective_from} /> –{" "}
                          {version.effective_to ? (
                            <CompanyDate value={version.effective_to} />
                          ) : (
                            "open"
                          )}
                        </TableCell>
                        <TableCell className="text-foreground">
                          Grace {version.grace_in_minutes} / {version.grace_out_minutes} minutes,{" "}
                          {version.hour_bands.length} hour bands
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )
          ) : null}
        </>
      ) : null}

      {publishOpen ? (
        <PublishAssignDialog
          policyKind="ATTENDANCE_POLICY"
          policyId={params.id}
          today={today}
          initialDate={initialPublishDate()}
          notBefore={current?.effective_from ?? null}
          saving={publishing}
          error={publishError}
          onCancel={() => setPublishOpen(false)}
          onConfirm={(choice) => void handlePublish(choice)}
        />
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
                ? "This policy can no longer be assigned to anyone new. Existing assignments are unaffected."
                : "This policy can be assigned again."}
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

      <Dialog open={discardOpen} onOpenChange={(open) => (!discarding ? setDiscardOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Discard this draft?</DialogTitle>
            <DialogDescription>
              This removes the unpublished changes. The live rules, if any, are unaffected.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDiscardOpen(false)}
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
    </div>
  );
}
