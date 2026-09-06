"use client";

import { GitMerge } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { LeaveCombinationRuleForm } from "@/components/leave-combination-rule/leave-combination-rule-form";
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
import type { LeaveCombinationRule } from "@/lib/leave-combination-rule/types";
import {
  EMPTY_LEAVE_COMBINATION_RULE_FORM_VALUES,
  buildLeaveCombinationRuleCreatePayload,
  validateLeaveCombinationRuleForm,
  type LeaveCombinationRuleFormErrors,
  type LeaveCombinationRuleFormValues,
} from "@/lib/leave-combination-rule/validate-leave-combination-rule";
import type { LeaveType } from "@/lib/leave-type/types";

export default function LeaveCombinationRulesPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("LEAVE.COMBINATION_RULE_MANAGE");

  const [rules, setRules] = useState<LeaveCombinationRule[] | null>(null);
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [values, setValues] = useState<LeaveCombinationRuleFormValues>(
    EMPTY_LEAVE_COMBINATION_RULE_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<LeaveCombinationRuleFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const leaveTypeById = useMemo(() => {
    const map = new Map<string, LeaveType>();
    for (const lt of leaveTypes) map.set(lt.id, lt);
    return map;
  }, [leaveTypes]);

  function leaveTypeLabel(id: string): string {
    const lt = leaveTypeById.get(id);
    return lt ? `${lt.name} (${lt.code})` : id;
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<LeaveCombinationRule[]>("/leave-combination-rules");
      setRules(data);
    } catch (err) {
      setRules(null);
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
    void apiClient
      .get<LeaveType[]>("/leave-types")
      .then(setLeaveTypes)
      .catch(() => setLeaveTypes([]));
  }, [load]);

  function openCreate() {
    setValues(EMPTY_LEAVE_COMBINATION_RULE_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateLeaveCombinationRuleForm(values);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }
    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<LeaveCombinationRule>(
        "/leave-combination-rules",
        buildLeaveCombinationRuleCreatePayload(values),
      );
      setCreateOpen(false);
      toast({ title: "Combination rule added", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast({
          title: "A rule for this pair of leave types already exists",
          description: "Delete the existing rule first if you want to change it.",
          variant: "danger",
        });
        return;
      }
      if (err instanceof ApiError && err.status === 404) {
        toast({ title: "One of these leave types could not be found", variant: "danger" });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({
          title: "You don't have permission to manage combination rules",
          variant: "danger",
        });
        return;
      }
      toast({
        title: "Could not add combination rule",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(rule: LeaveCombinationRule) {
    setDeletingId(rule.id);
    try {
      await apiClient.delete(`/leave-combination-rules/${rule.id}`);
      toast({ title: "Combination rule removed", variant: "success" });
      await load();
    } catch (err) {
      toast({
        title: "Could not remove combination rule",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Leave Combination Rules"
        description="Whether two leave types may be applied for on overlapping dates — e.g. Casual + Sick not allowed, Annual + Casual allowed. No rule for a pair means allowed."
        actions={
          canManage && rules && rules.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              Add Rule
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading combination rules…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view combination rules."
                  : error.message
              }
              onRetry={() => void load()}
            />
          ) : null}

          {!loading && !error && rules && rules.length === 0 ? (
            <EmptyState
              icon={GitMerge}
              title="No combination rules configured yet."
              description="Every pair of leave types is allowed to overlap by default. Add a rule only where a pair should be blocked (or explicitly allowed for clarity)."
              action={
                canManage ? (
                  <Button type="button" onClick={openCreate}>
                    Add Rule
                  </Button>
                ) : undefined
              }
            />
          ) : null}

          {!loading && !error && rules && rules.length > 0 ? (
            <ul className="divide-y divide-border">
              {rules.map((rule) => (
                <li
                  key={rule.id}
                  className="flex items-center justify-between gap-4 py-4 first:pt-0 last:pb-0"
                >
                  <div>
                    <p className="text-sm font-medium text-foreground">
                      {leaveTypeLabel(rule.leave_type_id_a)} + {leaveTypeLabel(rule.leave_type_id_b)}
                    </p>
                    {rule.reason ? (
                      <p className="mt-0.5 text-xs text-foreground-muted">{rule.reason}</p>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={rule.allowed ? "secondary" : "outline"}>
                      {rule.allowed ? "Allowed" : "Not allowed"}
                    </Badge>
                    {canManage ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={deletingId === rule.id}
                        onClick={() => void handleDelete(rule)}
                      >
                        {deletingId === rule.id ? "Removing…" : "Remove"}
                      </Button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Add Combination Rule</DialogTitle>
          </DialogHeader>
          <LeaveCombinationRuleForm
            values={values}
            errors={formErrors}
            onChange={setValues}
            leaveTypeOptions={leaveTypes}
            idPrefix="create-"
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleCreate()} disabled={saving}>
              {saving ? "Adding…" : "Add rule"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
