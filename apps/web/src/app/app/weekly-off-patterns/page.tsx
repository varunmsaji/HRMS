"use client";

import { CalendarOff } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { WeeklyOffPatternForm } from "@/components/weekly-off-pattern/weekly-off-pattern-form";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
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
import type { WeeklyOffPattern } from "@/lib/weekly-off-pattern/types";
import { WEEKDAY_LABELS } from "@/lib/weekly-off-pattern/types";
import {
  EMPTY_WEEKLY_OFF_PATTERN_FORM_VALUES,
  buildCreatePayload,
  validateWeeklyOffPatternForm,
  type WeeklyOffPatternFormErrors,
  type WeeklyOffPatternFormValues,
} from "@/lib/weekly-off-pattern/validate-weekly-off-pattern";

export default function WeeklyOffPatternsPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("ORG.CALENDAR.MANAGE");

  const [patterns, setPatterns] = useState<WeeklyOffPattern[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<WeeklyOffPatternFormValues>(
    EMPTY_WEEKLY_OFF_PATTERN_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<WeeklyOffPatternFormErrors>({});
  const [saving, setSaving] = useState(false);

  const loadPatterns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<WeeklyOffPattern[]>("/weekly-off-patterns");
      setPatterns(data);
    } catch (err) {
      setPatterns(null);
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
    void loadPatterns();
  }, [loadPatterns]);

  function openCreate() {
    setFormValues(EMPTY_WEEKLY_OFF_PATTERN_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateWeeklyOffPatternForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<WeeklyOffPattern>(
        "/weekly-off-patterns",
        buildCreatePayload(formValues),
      );
      setCreateOpen(false);
      toast({ title: "Weekly-off pattern added", variant: "success" });
      await loadPatterns();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({
          rules:
            err.code === "WEEKLY_OFF_RULE_INVALID"
              ? err.message
              : formErrors.rules,
        });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({
          title: "You don't have permission to add weekly-off patterns",
          variant: "danger",
        });
        return;
      }
      toast({
        title: "Could not add weekly-off pattern",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Weekly-Off Patterns"
        description="Configurable weekly-off rules — every Sunday, alternate Saturday, 2nd & 4th Saturday, and more."
        actions={
          canManage && patterns && patterns.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              Add Weekly-Off Pattern
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading weekly-off patterns…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view weekly-off patterns."
                  : error.message
              }
              onRetry={() => void loadPatterns()}
            />
          ) : null}

          {!loading && !error && patterns && patterns.length === 0 ? (
            <EmptyState
              icon={CalendarOff}
              title="No weekly-off patterns have been configured yet."
              description="Add a pattern such as every Sunday, alternate Saturday, or 2nd & 4th Saturday."
              action={
                canManage ? (
                  <Button type="button" onClick={openCreate}>
                    Add Weekly-Off Pattern
                  </Button>
                ) : undefined
              }
            />
          ) : null}

          {!loading && !error && patterns && patterns.length > 0 ? (
            <ul className="divide-y divide-border">
              {patterns.map((pattern) => (
                <li key={pattern.id} className="py-4 first:pt-0 last:pb-0">
                  <Link
                    href={`/app/weekly-off-patterns/${pattern.id}`}
                    className="flex items-center justify-between gap-4 rounded-md px-2 py-1 -mx-2 hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <div>
                      <p className="text-sm font-medium text-foreground">{pattern.name}</p>
                      <p className="mt-0.5 text-xs text-foreground-muted">
                        {pattern.pattern_kind.replace("_", " ")} ·{" "}
                        {pattern.rules.map((r) => WEEKDAY_LABELS[r.weekday]).join(", ")}
                      </p>
                    </div>
                    <Badge variant={pattern.is_active ? "secondary" : "outline"}>
                      {pattern.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Add Weekly-Off Pattern</DialogTitle>
          </DialogHeader>
          <div className="max-h-[65vh] overflow-y-auto pr-1">
            <WeeklyOffPatternForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
              idPrefix="create-"
            />
          </div>
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
              {saving ? "Adding…" : "Add pattern"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
