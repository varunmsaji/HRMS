"use client";

import { Clock, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ShiftForm } from "@/components/shift/shift-form";
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
import { DEFAULT_TIMEZONE } from "@/lib/timezones";
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
  // A multi-step create can fail part-way (shift created, publish rejected). Remember what
  // already succeeded so a retry from the same dialog resumes instead of duplicating rows.
  const [createdShift, setCreatedShift] = useState<Shift | null>(null);
  const [createdDraft, setCreatedDraft] = useState<{
    id: string;
    version: number;
  } | null>(null);
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

  function openCreate() {
    setFormValues(EMPTY_SHIFT_FORM_VALUES);
    setFormErrors({});
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
      now.getDate(),
    ).padStart(2, "0")}`;
    setVersionValues({
      ...EMPTY_SHIFT_VERSION_FORM_VALUES,
      timezone: DEFAULT_TIMEZONE,
      effectiveFrom: today,
    });
    setVersionErrors({});
    setCreatedShift(null);
    setCreatedDraft(null);
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
    let shift = createdShift;
    let draft = createdDraft;
    try {
      if (!shift) {
        shift = await apiClient.post<Shift>(
          "/shifts",
          buildCreatePayload(formValues),
        );
        setCreatedShift(shift);
      }
      // `POST /shifts` already opened an empty draft version — fill it rather than creating one.
      if (!draft) {
        if (!shift.draft_version_id)
          throw new Error("The new shift has no draft schedule.");
        draft = { id: shift.draft_version_id, version: 1 };
      }
      const filled = await apiClient.patch<ShiftVersion>(
        `/shifts/${shift.id}/versions/${draft.id}`,
        buildShiftVersionPatch(versionValues, null),
        { ifMatch: String(draft.version) },
      );
      draft = { id: filled.id, version: filled.version };
      setCreatedDraft(draft);
      await apiClient.post<ShiftVersion>(
        `/shifts/${shift.id}/versions/${draft.id}/publish`,
        { publish_reason: null },
        { ifMatch: String(draft.version) },
      );
      setCreateOpen(false);
      toast({
        title: "Shift added and schedule published",
        variant: "success",
      });
      await loadShifts();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        if (!shift) {
          setFormErrors({ name: getFieldError(err.details, "name") });
        } else {
          setVersionErrors(mapShiftVersionApiErrors(err.details));
        }
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({
          title: "You don't have permission to add shifts",
          variant: "danger",
        });
        return;
      }
      if (shift) {
        // The shift (and possibly its draft) exist; keep the dialog open so the user can fix
        // the schedule and retry, and make sure the list shows what was already created.
        await loadShifts();
        toast({
          title: "Shift added, but its schedule isn't published yet",
          description: describeApiError(err),
          variant: "danger",
        });
        return;
      }
      toast({
        title: "Could not add shift",
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
              {saving
                ? "Adding…"
                : createdShift
                  ? "Retry publish"
                  : "Add & publish"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
