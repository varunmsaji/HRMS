"use client";

import { Tag } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { LeaveTypeForm } from "@/components/leave-type/leave-type-form";
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
import { usePermissions } from "@/lib/auth/use-permissions";
import type { LeaveType } from "@/lib/leave-type/types";
import {
  EMPTY_LEAVE_TYPE_FORM_VALUES,
  buildLeaveTypeCreatePayload,
  buildLeaveTypeUpdatePatch,
  leaveTypeToFormValues,
  validateLeaveTypeForm,
  type LeaveTypeFormErrors,
  type LeaveTypeFormValues,
} from "@/lib/leave-type/validate-leave-type";

export default function LeaveTypesPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("LEAVE.TYPE_MANAGE");

  const [leaveTypes, setLeaveTypes] = useState<LeaveType[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [createValues, setCreateValues] = useState<LeaveTypeFormValues>(
    EMPTY_LEAVE_TYPE_FORM_VALUES,
  );
  const [createErrors, setCreateErrors] = useState<LeaveTypeFormErrors>({});
  const [creating, setCreating] = useState(false);

  const [editing, setEditing] = useState<LeaveType | null>(null);
  const [editValues, setEditValues] = useState<LeaveTypeFormValues | null>(null);
  const [editErrors, setEditErrors] = useState<LeaveTypeFormErrors>({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<LeaveType[]>("/leave-types");
      setLeaveTypes(data);
    } catch (err) {
      setLeaveTypes(null);
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
    setCreateValues(EMPTY_LEAVE_TYPE_FORM_VALUES);
    setCreateErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateLeaveTypeForm(createValues);
    if (Object.keys(clientErrors).length > 0) {
      setCreateErrors(clientErrors);
      return;
    }
    setCreating(true);
    setCreateErrors({});
    try {
      await apiClient.post<LeaveType>("/leave-types", buildLeaveTypeCreatePayload(createValues));
      setCreateOpen(false);
      toast({ title: "Leave type added", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setCreateErrors({ code: "A leave type with this code already exists." });
        return;
      }
      if (err instanceof ApiError && err.status === 422) {
        setCreateErrors({
          code: getFieldError(err.details, "code"),
          name: getFieldError(err.details, "name"),
        });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to add leave types", variant: "danger" });
        return;
      }
      toast({ title: "Could not add leave type", description: describeApiError(err), variant: "danger" });
    } finally {
      setCreating(false);
    }
  }

  function openEdit(leaveType: LeaveType) {
    setEditing(leaveType);
    setEditValues(leaveTypeToFormValues(leaveType));
    setEditErrors({});
  }

  async function handleSaveEdit() {
    if (!editing || !editValues) return;
    const clientErrors = validateLeaveTypeForm(editValues);
    if (Object.keys(clientErrors).length > 0) {
      setEditErrors(clientErrors);
      return;
    }
    const patch = buildLeaveTypeUpdatePatch(editValues, editing);
    if (Object.keys(patch).length === 0) {
      setEditing(null);
      toast({ title: "No changes to save", variant: "default" });
      return;
    }
    setSaving(true);
    setEditErrors({});
    try {
      await apiClient.patch<LeaveType>(`/leave-types/${editing.id}`, patch, {
        ifMatch: String(editing.version),
      });
      setEditing(null);
      toast({ title: "Leave type saved", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === "STALE_RESOURCE") {
        toast({
          title: "This leave type was changed by someone else",
          description: "Reload the page and try again.",
          variant: "danger",
        });
        return;
      }
      if (err instanceof ApiError && err.status === 422) {
        setEditErrors({ name: getFieldError(err.details, "name") });
        return;
      }
      toast({ title: "Could not save leave type", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  async function handleToggleActive(leaveType: LeaveType) {
    try {
      await apiClient.patch<LeaveType>(
        `/leave-types/${leaveType.id}`,
        { is_active: !leaveType.is_active },
        { ifMatch: String(leaveType.version) },
      );
      toast({
        title: leaveType.is_active ? "Leave type deactivated" : "Leave type reactivated",
        variant: "success",
      });
      await load();
    } catch (err) {
      toast({ title: "Could not update leave type", description: describeApiError(err), variant: "danger" });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Leave Types"
        description="The kinds of leave employees can apply for — Casual, Earned, Sick, and any LOP-style type that doesn't consume a balance."
        actions={
          canManage && leaveTypes && leaveTypes.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              Add Leave Type
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading leave types…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view leave types."
                  : error.message
              }
              onRetry={() => void load()}
            />
          ) : null}

          {!loading && !error && leaveTypes && leaveTypes.length === 0 ? (
            <EmptyState
              icon={Tag}
              title="No leave types have been configured yet."
              description="Add a leave type, then configure its accrual/approval rules via a Leave Policy."
              action={
                canManage ? (
                  <Button type="button" onClick={openCreate}>
                    Add Leave Type
                  </Button>
                ) : undefined
              }
            />
          ) : null}

          {!loading && !error && leaveTypes && leaveTypes.length > 0 ? (
            <ul className="divide-y divide-border">
              {leaveTypes.map((leaveType) => (
                <li key={leaveType.id} className="flex items-center justify-between gap-4 py-4 first:pt-0 last:pb-0">
                  <button
                    type="button"
                    onClick={() => (canManage ? openEdit(leaveType) : undefined)}
                    className="flex-1 rounded-md px-2 py-1 -mx-2 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <p className="text-sm font-medium text-foreground">
                      {leaveType.name}{" "}
                      <span className="text-foreground-muted">({leaveType.code})</span>
                    </p>
                    <p className="mt-0.5 text-xs text-foreground-muted">
                      {leaveType.is_paid_default ? "Paid" : "Unpaid"} ·{" "}
                      {leaveType.requires_balance ? "Balance-backed" : "No balance (LOP-style)"}
                    </p>
                  </button>
                  <div className="flex items-center gap-2">
                    <Badge variant={leaveType.is_active ? "secondary" : "outline"}>
                      {leaveType.is_active ? "Active" : "Inactive"}
                    </Badge>
                    {canManage ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => void handleToggleActive(leaveType)}
                      >
                        {leaveType.is_active ? "Deactivate" : "Reactivate"}
                      </Button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={(open) => (!creating ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Add Leave Type</DialogTitle>
          </DialogHeader>
          <LeaveTypeForm
            values={createValues}
            errors={createErrors}
            onChange={setCreateValues}
            idPrefix="create-"
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)} disabled={creating}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleCreate()} disabled={creating}>
              {creating ? "Adding…" : "Add leave type"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={editing !== null} onOpenChange={(open) => (!saving && !open ? setEditing(null) : null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Edit Leave Type</DialogTitle>
          </DialogHeader>
          {editValues ? (
            <LeaveTypeForm
              values={editValues}
              errors={editErrors}
              onChange={setEditValues}
              idPrefix="edit-"
              codeEditable={false}
            />
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setEditing(null)} disabled={saving}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleSaveEdit()} disabled={saving}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
