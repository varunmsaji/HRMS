"use client";

import { Clock } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ShiftForm } from "@/components/shift/shift-form";
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
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { Shift } from "@/lib/shift/types";
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
  const [formValues, setFormValues] = useState<ShiftFormValues>(EMPTY_SHIFT_FORM_VALUES);
  const [formErrors, setFormErrors] = useState<ShiftFormErrors>({});
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
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
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
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateShiftForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<Shift>("/shifts", buildCreatePayload(formValues));
      setCreateOpen(false);
      toast({ title: "Shift added — configure its schedule on the Versions tab", variant: "success" });
      await loadShifts();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({ name: getFieldError(err.details, "name") });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to add shifts", variant: "danger" });
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
        title="Shifts"
        description="Shift timings, breaks, and grace periods your company can assign later."
        actions={
          shifts && shifts.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              Add Shift
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading shifts…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403 ? "You do not have permission to view shifts." : error.message
              }
              onRetry={() => void loadShifts()}
            />
          ) : null}

          {!loading && !error && shifts && shifts.length === 0 ? (
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
          ) : null}

          {!loading && !error && shifts && shifts.length > 0 ? (
            <ul className="divide-y divide-border">
              {shifts.map((shift) => (
                <li key={shift.id} className="py-4 first:pt-0 last:pb-0">
                  <Link
                    href={`/app/shifts/${shift.id}`}
                    className="flex items-center justify-between gap-4 rounded-md px-2 py-1 -mx-2 hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <div>
                      <p className="text-sm font-medium text-foreground">
                        {shift.name}
                        {shift.code ? (
                          <span className="text-foreground-muted"> ({shift.code})</span>
                        ) : null}
                      </p>
                      <p className="mt-0.5 flex gap-2 text-xs text-foreground-muted">
                        {shift.current_version_id ? (
                          <span>Published schedule</span>
                        ) : (
                          <span>No published schedule</span>
                        )}
                        {shift.draft_version_id ? <span>· Draft in progress</span> : null}
                      </p>
                    </div>
                    <Badge variant={shift.is_active ? "secondary" : "outline"}>
                      {shift.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Shift</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <ShiftForm values={formValues} errors={formErrors} onChange={setFormValues} idPrefix="create-" />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleCreate()} disabled={saving}>
              {saving ? "Adding…" : "Add shift"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
