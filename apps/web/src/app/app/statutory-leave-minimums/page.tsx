"use client";

import { Scale } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { StatutoryLeaveMinimumForm } from "@/components/statutory-leave-minimum/statutory-leave-minimum-form";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  EMPTY_STATUTORY_LEAVE_MINIMUM_FORM_VALUES,
  buildStatutoryLeaveMinimumCreatePayload,
  validateStatutoryLeaveMinimumForm,
  type StatutoryLeaveMinimumFormErrors,
  type StatutoryLeaveMinimumFormValues,
} from "@/lib/statutory-leave-minimum/validate-statutory-leave-minimum";
import type { StatutoryLeaveMinimum } from "@/lib/statutory-leave-minimum/types";

export default function StatutoryLeaveMinimumsPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("LEAVE.STATUTORY_MINIMUM_MANAGE");

  const [minimums, setMinimums] = useState<StatutoryLeaveMinimum[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [values, setValues] = useState<StatutoryLeaveMinimumFormValues>(
    EMPTY_STATUTORY_LEAVE_MINIMUM_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<StatutoryLeaveMinimumFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<StatutoryLeaveMinimum[]>("/statutory-leave-minimums");
      setMinimums(data);
    } catch (err) {
      setMinimums(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setValues(EMPTY_STATUTORY_LEAVE_MINIMUM_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateStatutoryLeaveMinimumForm(values);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }
    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<StatutoryLeaveMinimum>(
        "/statutory-leave-minimums",
        buildStatutoryLeaveMinimumCreatePayload(values),
      );
      setCreateOpen(false);
      toast({ title: "Statutory minimum added", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({
          title: "You don't have permission to manage statutory minimums",
          variant: "danger",
        });
        return;
      }
      toast({
        title: "Could not add statutory minimum",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(minimum: StatutoryLeaveMinimum) {
    setDeletingId(minimum.id);
    try {
      await apiClient.delete(`/statutory-leave-minimums/${minimum.id}`);
      toast({ title: "Statutory minimum removed", variant: "success" });
      await load();
    } catch (err) {
      toast({
        title: "Could not remove statutory minimum",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setDeletingId(null);
    }
  }

  function scopeLabel(minimum: StatutoryLeaveMinimum): string {
    const parts = [minimum.state_code, minimum.establishment_type].filter(Boolean);
    return parts.length > 0 ? parts.join(" · ") : "All states / establishment types";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Statutory Leave Minimums"
        description="The legal compliance floor (client spec §16) — a leave policy cannot be published below the strictest minimum configured here for its leave type's statutory category. No figures are pre-filled; enter the minimums that apply to your states."
        actions={
          canManage && minimums && minimums.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              Add Minimum
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading statutory minimums…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view statutory minimums."
                  : error.message
              }
              onRetry={() => void load()}
            />
          ) : null}

          {!loading && !error && minimums && minimums.length === 0 ? (
            <EmptyState
              icon={Scale}
              title="No statutory minimums configured yet."
              description="Until a minimum is added for a leave category, publishing a policy in that category is unaffected."
              action={
                canManage ? (
                  <Button type="button" onClick={openCreate}>
                    Add Minimum
                  </Button>
                ) : undefined
              }
            />
          ) : null}

          {!loading && !error && minimums && minimums.length > 0 ? (
            <ul className="divide-y divide-border">
              {minimums.map((minimum) => (
                <li
                  key={minimum.id}
                  className="flex items-center justify-between gap-4 py-4 first:pt-0 last:pb-0"
                >
                  <div>
                    <p className="text-sm font-medium text-foreground">
                      {minimum.leave_category} — {minimum.min_days_per_year} days / year
                    </p>
                    <p className="mt-0.5 text-xs text-foreground-muted">{scopeLabel(minimum)}</p>
                    {minimum.note ? (
                      <p className="mt-0.5 text-xs text-foreground-muted">{minimum.note}</p>
                    ) : null}
                  </div>
                  {canManage ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={deletingId === minimum.id}
                      onClick={() => void handleDelete(minimum)}
                    >
                      {deletingId === minimum.id ? "Removing…" : "Remove"}
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Add Statutory Minimum</DialogTitle>
          </DialogHeader>
          <StatutoryLeaveMinimumForm
            values={values}
            errors={formErrors}
            onChange={setValues}
            idPrefix="create-"
          />
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setCreateOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleCreate()} disabled={saving}>
              {saving ? "Adding…" : "Add minimum"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
