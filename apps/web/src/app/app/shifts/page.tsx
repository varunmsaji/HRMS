"use client";

import { Clock, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ShiftForm } from "@/components/shift/shift-form";
import { SHIFT_TEMPLATES } from "@/lib/shift/templates";
import { cn } from "@/lib/utils";
import { ShiftVersionForm } from "@/components/shift/shift-version-form";
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
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { Shift, ShiftVersion } from "@/lib/shift/types";
import type { WeeklyOffPattern } from "@/lib/weekly-off-pattern/types";
import {
  EMPTY_SHIFT_VERSION_FORM_VALUES,
  buildShiftVersionPatch,
  mapShiftVersionApiErrors,
  validateShiftVersionForm,
  type ShiftVersionFormErrors,
  type ShiftVersionFormValues,
} from "@/lib/shift/validate-shift-version";
import {
  EMPTY_SHIFT_FORM_VALUES,
  buildCreatePayload,
  validateShiftForm,
  type ShiftFormErrors,
  type ShiftFormValues,
} from "@/lib/shift/validate-shift";

export default function ShiftsPage() {
  const { toast } = useToast();
  const [shifts, setShifts] = useState<Shift[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<ShiftFormValues>(
    EMPTY_SHIFT_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<ShiftFormErrors>({});
  const [versionValues, setVersionValues] = useState<ShiftVersionFormValues>(
    EMPTY_SHIFT_VERSION_FORM_VALUES,
  );
  const [versionErrors, setVersionErrors] = useState<ShiftVersionFormErrors>(
    {},
  );
  const [weeklyOffPatterns, setWeeklyOffPatterns] = useState<
    WeeklyOffPattern[]
  >([]);
  const [templateKey, setTemplateKey] = useState(SHIFT_TEMPLATES[0].key);
  const [saving, setSaving] = useState(false);

  const loadShifts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<Shift[]>("/shifts");
      setShifts(data);
    } catch (err) {
      setShifts(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({
              status: 0,
              code: "UNKNOWN_ERROR",
              message: "Something went wrong.",
            }),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadShifts();
  }, [loadShifts]);

  function applyTemplate(key: string, currentName: string, currentKey: string) {
    const template = SHIFT_TEMPLATES.find((t) => t.key === key);
    if (!template) return;
    const nameIsUntouched = SHIFT_TEMPLATES.some(
      (t) => t.key === currentKey && t.defaultName === currentName,
    );
    setTemplateKey(key);
    setVersionValues((prev) => ({ ...template.values, effectiveFrom: prev.effectiveFrom }));
    setVersionErrors({});
    if (nameIsUntouched) setFormValues((prev) => ({ ...prev, name: template.defaultName }));
  }

  function openCreate() {
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
      now.getDate(),
    ).padStart(2, "0")}`;
    const first = SHIFT_TEMPLATES[0];
    setFormValues({ ...EMPTY_SHIFT_FORM_VALUES, name: first.defaultName });
    setFormErrors({});
    setTemplateKey(first.key);
    setVersionValues({ ...first.values, effectiveFrom: today });
    setVersionErrors({});
    setCreateOpen(true);
    apiClient
      .get<WeeklyOffPattern[]>("/weekly-off-patterns")
      .then(setWeeklyOffPatterns)
      .catch(() => setWeeklyOffPatterns([]));
  }

  async function handleCreate() {
    const clientErrors = validateShiftForm(formValues);
    const clientVersionErrors = validateShiftVersionForm(versionValues);
    if (
      Object.keys(clientErrors).length > 0 ||
      Object.keys(clientVersionErrors).length > 0
    ) {
      setFormErrors(clientErrors);
      setVersionErrors(clientVersionErrors);
      return;
    }

    setSaving(true);
    setFormErrors({});
    setVersionErrors({});
    try {
      // One request: either the shift exists with its published schedule, or nothing was saved.
      await apiClient.post("/shifts/setup", {
        name: buildCreatePayload(formValues).name,
        rules: buildShiftVersionPatch(versionValues, null),
        publish: true,
      });
      setCreateOpen(false);
      toast({ title: "Shift added and schedule published", variant: "success" });
      await loadShifts();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to add shifts", variant: "danger" });
        return;
      }
      if (err instanceof ApiError && err.status === 422) {
        const nameProblem = getFieldError(err.details, "name");
        if (nameProblem) setFormErrors({ name: nameProblem });
        setVersionErrors(mapShiftVersionApiErrors(err.details));
      }
      toast({
        title: "Nothing was saved",
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
        backHref="/app/settings/attendance"
        backLabel="Attendance"
        title="Shifts"
        description="Shift timings, breaks, and grace periods your company can assign later."
        actions={
          shifts && shifts.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add Shift
            </Button>
          ) : null
        }
      />

      <TableContainer>
        {loading ? <LoadingState label="Loading shifts…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view shifts."
                  : error.message
              }
              onRetry={() => void loadShifts()}
            />
          </div>
        ) : null}

        {!loading && !error && shifts && shifts.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={Clock}
              title="No shifts have been configured yet."
              description="Add the shift timings your company will assign later."
              action={
                <Button type="button" onClick={openCreate}>
                  Add Shift
                </Button>
              }
            />
          </div>
        ) : null}

        {!loading && !error && shifts && shifts.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Shift</TableHead>
                <TableHead>Schedule version</TableHead>
                <TableHead>Status</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shifts.map((shift) => (
                <TableRow key={shift.id}>
                  <TableCell>
                    <Link
                      href={`/app/shifts/${shift.id}`}
                      className="font-medium text-foreground hover:text-primary hover:underline"
                    >
                      {shift.name}
                      {shift.code ? (
                        <span className="ml-1.5 font-mono text-xs text-foreground-muted">
                          ({shift.code})
                        </span>
                      ) : null}
                    </Link>
                  </TableCell>
                  <TableCell className="text-xs text-foreground-secondary">
                    <span className="inline-flex items-center gap-2">
                      {shift.current_version_id ? (
                        <span>Published schedule</span>
                      ) : (
                        <span>No published schedule</span>
                      )}
                      {shift.draft_version_id ? (
                        <Badge variant="warning">Draft in progress</Badge>
                      ) : null}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge variant={shift.is_active ? "secondary" : "outline"}>
                      {shift.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell align="right">
                    <TableRowAction href={`/app/shifts/${shift.id}`}>Configure</TableRowAction>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </TableContainer>

      <Dialog
        open={createOpen}
        onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Shift</DialogTitle>
          </DialogHeader>
          <div className="max-h-[70vh] overflow-y-auto pr-1">
            <div className="mb-6 space-y-2">
              <h3 className="text-sm font-medium text-foreground">Start from</h3>
              <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Start from">
                {SHIFT_TEMPLATES.map((template) => (
                  <label
                    key={template.key}
                    className={cn(
                      "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors",
                      templateKey === template.key
                        ? "border-primary bg-primary-subtle"
                        : "border-border hover:border-primary/40",
                    )}
                  >
                    <input
                      type="radio"
                      name="shift-template"
                      className="mt-1"
                      checked={templateKey === template.key}
                      onChange={() => applyTemplate(template.key, formValues.name, templateKey)}
                    />
                    <span>
                      <span className="block text-sm font-medium text-foreground">
                        {template.label}
                      </span>
                      <span className="block text-xs text-foreground-secondary">
                        {template.description}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
            <ShiftForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
              idPrefix="create-"
            />
            <div className="mt-6">
              <ShiftVersionForm
                values={versionValues}
                errors={versionErrors}
                onChange={setVersionValues}
                weeklyOffPatterns={weeklyOffPatterns}
              />
            </div>
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
            <Button
              type="button"
              onClick={() => void handleCreate()}
              disabled={saving}
            >
              {saving ? "Adding…" : "Add & publish"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
