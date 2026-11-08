"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { WeeklyOffPatternForm } from "@/components/weekly-off-pattern/weekly-off-pattern-form";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { PolicyFollowersPanel } from "@/components/policy-assignment/policy-followers-panel";
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
import { describeDeactivationBlocked } from "@/lib/work-calendar/deactivation";
import { ChangeImpactDialog } from "@/components/work-calendar/change-impact-dialog";
import type { ProposedChange } from "@/lib/work-calendar/change-impact";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { WeeklyOffPattern } from "@/lib/weekly-off-pattern/types";
import { WEEKDAY_LABELS } from "@/lib/weekly-off-pattern/types";
import {
  buildUpdatePatch,
  validateWeeklyOffPatternForm,
  weeklyOffPatternToFormValues,
  type WeeklyOffPatternFormErrors,
  type WeeklyOffPatternFormValues,
} from "@/lib/weekly-off-pattern/validate-weekly-off-pattern";

export default function WeeklyOffPatternDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const { can } = usePermissions();
  const [impact, setImpact] = useState<{
    change: ProposedChange;
    title: string;
    onDone: () => void | Promise<void>;
  } | null>(null);

  const canManage = can("ORG.CALENDAR.MANAGE");
  const { user } = useAuth();
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");

  const [pattern, setPattern] = useState<WeeklyOffPattern | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<WeeklyOffPatternFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<WeeklyOffPatternFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [statusChanging, setStatusChanging] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<WeeklyOffPattern>(`/weekly-off-patterns/${params.id}`);
      setPattern(data);
      return data;
    } catch (err) {
      setPattern(null);
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

  useEffect(() => {
    void load();
  }, [load]);

  function startEditing() {
    if (!pattern) return;
    setFormValues(weeklyOffPatternToFormValues(pattern));
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
    if (!pattern || !formValues) return;
    const clientErrors = validateWeeklyOffPatternForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    setFormErrors({});
    setStaleMessage(null);
    setImpact({
      change: {
        change_type: "WEEKLY_OFF_PATTERN_UPDATE",
        pattern_id: pattern.id,
        expected_version: pattern.version,
        patch: buildUpdatePatch(formValues, pattern),
      },
      title: "Save weekly-off pattern",
      onDone: async () => {
        setEditing(false);
        setFormValues(null);
        toast({ title: "Weekly-off pattern saved", variant: "success" });
        await load();
      },
    });
  }

  async function reloadLatest() {
    const latest = await load();
    if (latest) {
      setEditing(false);
      setFormValues(null);
      setStaleMessage(null);
      toast({ title: "Reloaded", variant: "success" });
    }
  }

  async function handleToggleStatus() {
    if (!pattern) return;
    setStatusChanging(true);
    try {
      if (pattern.is_active) {
        const updated = await apiClient.delete<WeeklyOffPattern>(
          `/weekly-off-patterns/${pattern.id}`,
          { ifMatch: String(pattern.version) },
        );
        setPattern(updated);
        toast({ title: "Weekly-off pattern deactivated", variant: "success" });
      } else {
        const updated = await apiClient.patch<WeeklyOffPattern>(
          `/weekly-off-patterns/${pattern.id}`,
          { is_active: true },
          { ifMatch: String(pattern.version) },
        );
        setPattern(updated);
        toast({ title: "Weekly-off pattern reactivated", variant: "success" });
      }
      setConfirmOpen(false);
    } catch (err) {
      const blocked = err instanceof ApiError ? describeDeactivationBlocked(err) : null;
      if (blocked) {
        toast({ title: "Cannot deactivate", description: blocked, variant: "danger" });
        setConfirmOpen(false);
        return;
      }
      toast({
        title: "Could not update status",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setStatusChanging(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/weekly-off-patterns"
        backLabel="Weekly-Off Patterns"
        title={pattern?.name ?? "Weekly-Off Pattern"}
        description="Typed weekly-off rules for this pattern."
        actions={
          canManage && pattern && !editing ? (
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)}>
                {pattern.is_active ? "Deactivate" : "Reactivate"}
              </Button>
              <Button type="button" onClick={startEditing}>
                Edit
              </Button>
            </div>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading weekly-off pattern…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this pattern."
                  : error.status === 404
                    ? "This weekly-off pattern could not be found."
                    : error.message
              }
              onRetry={error.status === 404 ? undefined : () => void load()}
            />
          ) : null}

          {staleMessage ? (
            <div className="mb-4 rounded-md border border-warning/30 bg-warning/5 p-4" role="alert">
              <p className="text-sm font-medium text-foreground">{staleMessage}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button type="button" size="sm" onClick={() => void reloadLatest()}>
                  Reload latest
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={cancelEditing}>
                  Cancel current changes
                </Button>
              </div>
            </div>
          ) : null}

          {!loading && !error && pattern && editing && formValues ? (
            <div className="space-y-6">
              <WeeklyOffPatternForm values={formValues} errors={formErrors} onChange={setFormValues} />
              <div className="flex flex-wrap gap-2">
                <Button type="button" onClick={() => void handleSave()} disabled={saving}>
                  {saving ? "Saving…" : "Save changes"}
                </Button>
                <Button type="button" variant="outline" onClick={cancelEditing} disabled={saving}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : null}

          {!loading && !error && pattern && !editing ? (
            <div className="space-y-4">
              <Badge variant={pattern.is_active ? "secondary" : "outline"}>
                {pattern.is_active ? "Active" : "Inactive"}
              </Badge>
              <p className="text-sm text-foreground-muted">
                {pattern.pattern_kind.replace("_", " ")}
              </p>
              <ul className="divide-y divide-border rounded-md border border-border">
                {pattern.rules.map((rule) => (
                  <li key={rule.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                    <span className="font-medium text-foreground">
                      {WEEKDAY_LABELS[rule.weekday]}
                    </span>
                    {rule.nth_in_month !== null ? (
                      <span className="text-foreground-muted">
                        ({rule.nth_in_month === -1 ? "last" : `${rule.nth_in_month}${
                          rule.nth_in_month === 1
                            ? "st"
                            : rule.nth_in_month === 2
                              ? "nd"
                              : rule.nth_in_month === 3
                                ? "rd"
                                : "th"
                        }`})
                      </span>
                    ) : null}
                    {rule.cycle_start_date ? (
                      <span className="text-foreground-muted">from {rule.cycle_start_date}</span>
                    ) : null}
                    <span className="text-foreground-muted">
                      {rule.off_fraction === "1.00" ? "full day" : "half day"} off
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {pattern ? (
        <section aria-labelledby="weekly-off-followers-title" className="space-y-3">
          <div>
            <h2 id="weekly-off-followers-title" className="text-md font-semibold text-foreground">
              Who follows this
            </h2>
            <p className="mt-0.5 text-sm text-foreground-secondary">
              Groups given this pattern directly. A work calendar can also include it.
            </p>
          </div>
          <PolicyFollowersPanel
            policyKind="WEEKLY_OFF"
            policyId={pattern.id}
            policyName={pattern.name}
            today={today}
            canManage={canManage}
            cannotAssignReason={
              pattern.is_active
                ? null
                : "This pattern is inactive, so nobody new can follow it. Reactivate it to assign it."
            }
          />
        </section>
      ) : null}

      <Dialog
        open={confirmOpen}
        onOpenChange={(open) => (!statusChanging ? setConfirmOpen(open) : null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {pattern?.is_active ? "Deactivate weekly-off pattern?" : "Reactivate weekly-off pattern?"}
            </DialogTitle>
            <DialogDescription>
              {pattern?.is_active
                ? "This pattern will no longer be assignable to new work calendars. You can reactivate it later."
                : "This pattern will become assignable again."}
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
              variant={pattern?.is_active ? "destructive" : "default"}
              onClick={() => void handleToggleStatus()}
              disabled={statusChanging}
            >
              {statusChanging ? "Saving…" : pattern?.is_active ? "Deactivate" : "Reactivate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ChangeImpactDialog
        change={impact?.change ?? null}
        title={impact?.title ?? ""}
        onClose={() => setImpact(null)}
        onApplied={() => {
          const done = impact?.onDone;
          setImpact(null);
          void done?.();
        }}
      />
    </div>
  );
}
