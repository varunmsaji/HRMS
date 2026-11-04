"use client";

import { CalendarOff, Plus } from "lucide-react";
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
import {
  Dialog,
  DialogContent,
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
  TableRowAction,
} from "@/components/ui/table";
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
          rules: err.code === "WEEKLY_OFF_RULE_INVALID" ? err.message : formErrors.rules,
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
        backHref="/app/settings"
        backLabel="Settings"
        title="Weekly-Off Patterns"
        description="Configurable weekly-off rules — every Sunday, alternate Saturday, 2nd & 4th Saturday, and more."
        actions={
          canManage && patterns && patterns.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add Weekly-Off Pattern
            </Button>
          ) : null
        }
      />

      <TableContainer>
        {loading ? <LoadingState label="Loading weekly-off patterns…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view weekly-off patterns."
                  : error.message
              }
              onRetry={() => void loadPatterns()}
            />
          </div>
        ) : null}

        {!loading && !error && patterns && patterns.length === 0 ? (
          <div className="p-6">
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
          </div>
        ) : null}

        {!loading && !error && patterns && patterns.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Pattern</TableHead>
                <TableHead>Schedule</TableHead>
                <TableHead>Status</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {patterns.map((pattern) => (
                <TableRow key={pattern.id}>
                  <TableCell>
                    <Link
                      href={`/app/weekly-off-patterns/${pattern.id}`}
                      className="font-medium text-foreground hover:text-primary hover:underline"
                    >
                      {pattern.name}
                    </Link>
                  </TableCell>
                  <TableCell className="text-xs text-foreground-secondary">
                    {pattern.pattern_kind.replace("_", " ")} ·{" "}
                    {pattern.rules.map((r) => WEEKDAY_LABELS[r.weekday]).join(", ")}
                  </TableCell>
                  <TableCell>
                    <Badge variant={pattern.is_active ? "secondary" : "outline"}>
                      {pattern.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell align="right">
                    <TableRowAction href={`/app/weekly-off-patterns/${pattern.id}`}>Configure</TableRowAction>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </TableContainer>

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
