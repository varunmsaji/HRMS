import { useEffect, useMemo, useState } from "react";

import { BusyRegion } from "@/components/common/busy-region";
import { CompanyDate } from "@/components/common/company-date";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { useToast } from "@/components/common/toast";
import { EmployeeSelect } from "@/components/employee/employee-select";
import {
  EndAssignmentDialog,
  type EndTarget,
} from "@/components/policy-assignment/end-assignment-dialog";
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
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { TableSkeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ChangeImpactDialog } from "@/components/work-calendar/change-impact-dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import type { EmployeeDirectory } from "@/lib/employee/use-employee-directory";
import {
  appliedSourceLabel,
  canEndAssignment,
  coveragePath,
  coverageRowKey,
  coverageRowLabel,
  needsImpactPreview,
  POLICY_KIND_LIST_PATH,
  POLICY_KINDS,
  SCOPE_TYPE_LABELS,
  SCOPE_TYPES,
  type PolicyCoverage,
  type PolicyCoverageRow,
  type PolicyKind,
  type ScopeType,
} from "@/lib/policy-assignment/types";
import type { ProposedChange } from "@/lib/work-calendar/change-impact";

interface NamedOption {
  id: string;
  name?: string;
  title?: string;
  leave_type_id?: string;
  is_active?: boolean;
}

function optionLabel(option: NamedOption): string {
  return option.name ?? option.title ?? option.id;
}

const SCOPE_LIST_PATH: Partial<Record<ScopeType, string>> = {
  LEGAL_ENTITY: "/legal-entities",
  BRANCH: "/branches",
  DEPARTMENT: "/departments",
  GRADE: "/grades",
  DESIGNATION: "/designations",
  SHIFT: "/shifts",
};

/** The four versioned kinds can only be assigned once published; the API filters them. */
function assignablePath(kind: PolicyKind): string {
  return needsImpactPreview(kind)
    ? POLICY_KIND_LIST_PATH[kind]
    : `${POLICY_KIND_LIST_PATH[kind]}?assignable=true`;
}

interface Change {
  row: PolicyCoverageRow;
  policyId: string;
  policyName: string;
}

export function SetPoliciesPanel({
  directory,
  today,
}: {
  directory: EmployeeDirectory;
  today: string;
}) {
  const { toast } = useToast();
  const datePattern = useCompanyDatePattern();

  const [scopeType, setScopeType] = useState<ScopeType>("COMPANY");
  const [scopeId, setScopeId] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [result, setResult] = useState<{
    path: string;
    coverage: PolicyCoverage | null;
    error: ApiError | null;
  } | null>(null);

  const [optionsByKind, setOptionsByKind] = useState<Partial<Record<PolicyKind, NamedOption[]>>>({});
  const [scopeOptions, setScopeOptions] = useState<Partial<Record<ScopeType, NamedOption[]>>>({});

  const [picks, setPicks] = useState<Record<string, string>>({});
  const [effectiveFrom, setEffectiveFrom] = useState(today);
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const [reviewOpen, setReviewOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [impact, setImpact] = useState<{
    change: ProposedChange;
    title: string;
    rest: Change[];
  } | null>(null);
  const [ending, setEnding] = useState<EndTarget | null>(null);

  const ready = scopeType === "COMPANY" || Boolean(scopeId);
  const scopeRef = scopeType === "COMPANY" ? null : scopeId;
  const path = ready ? `${coveragePath(scopeType, scopeRef, today)}#${refresh}` : null;

  useEffect(() => {
    if (!path) return;
    let current = true;
    apiClient
      .get<PolicyCoverage>(path.split("#")[0])
      .then((coverage) => {
        if (current) setResult({ path, coverage, error: null });
      })
      .catch((err: unknown) => {
        if (!current) return;
        setResult({
          path,
          coverage: null,
          error:
            err instanceof ApiError
              ? err
              : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        });
      });
    return () => {
      current = false;
    };
  }, [path]);

  useEffect(() => {
    void Promise.all(
      POLICY_KINDS.map((kind) =>
        apiClient
          .get<NamedOption[]>(assignablePath(kind))
          .then((list) => list.filter((option) => option.is_active !== false))
          .catch(() => [] as NamedOption[]),
      ),
    ).then((lists) =>
      setOptionsByKind(Object.fromEntries(POLICY_KINDS.map((kind, i) => [kind, lists[i]]))),
    );
    const scopes = Object.entries(SCOPE_LIST_PATH);
    void Promise.all(
      scopes.map(([, listPath]) =>
        apiClient
          .get<NamedOption[]>(listPath)
          .then((list) => list.filter((option) => option.is_active !== false))
          .catch(() => [] as NamedOption[]),
      ),
    ).then((lists) =>
      setScopeOptions(Object.fromEntries(scopes.map(([scope], i) => [scope, lists[i]]))),
    );
  }, []);

  const showing = result && result.path === path ? result : null;
  // Keep the previous rows on screen during a refresh of the same scope.
  const coverage =
    showing?.coverage ??
    (result?.coverage &&
    result.coverage.scope_type === scopeType &&
    (result.coverage.scope_id ?? null) === scopeRef
      ? result.coverage
      : null);

  function rowOptions(row: PolicyCoverageRow): NamedOption[] {
    const all = (optionsByKind[row.policy_kind] ?? []).filter(
      (option) => !row.leave_type_id || option.leave_type_id === row.leave_type_id,
    );
    if (row.own && !all.some((option) => option.id === row.own?.policy_id)) {
      return [{ id: row.own.policy_id, name: row.own.policy_name ?? "Current policy" }, ...all];
    }
    return all;
  }

  const changes: Change[] = useMemo(() => {
    if (!coverage) return [];
    const found: Change[] = [];
    for (const row of coverage.rows) {
      const picked = picks[coverageRowKey(row)];
      if (!picked || picked === row.own?.policy_id) continue;
      const option = (optionsByKind[row.policy_kind] ?? []).find((o) => o.id === picked);
      found.push({ row, policyId: picked, policyName: option ? optionLabel(option) : "Selected policy" });
    }
    return found;
  }, [coverage, picks, optionsByKind]);

  function changeScope(nextType: ScopeType, nextId: string) {
    setScopeType(nextType);
    setScopeId(nextId);
    setPicks({});
    setFormError(null);
  }

  function openReview() {
    if (!effectiveFrom) {
      setFormError("Effective from is required.");
      return;
    }
    const tooEarly = changes.find(
      (change) => change.row.own && effectiveFrom <= change.row.own.effective_from,
    );
    if (tooEarly?.row.own) {
      setFormError(
        `${coverageRowLabel(tooEarly.row)} must start after ${formatCompanyDate(tooEarly.row.own.effective_from, datePattern)}, when its current assignment started.`,
      );
      return;
    }
    setFormError(null);
    setSaveError(null);
    setReviewOpen(true);
  }

  function reload() {
    setRefresh((n) => n + 1);
  }

  function impactFor(change: Change, rest: Change[]) {
    setImpact({
      title: `Change ${coverageRowLabel(change.row)}`,
      rest,
      change: {
        change_type: "ASSIGNMENT_CREATE",
        expected_version: change.row.own?.version,
        body: {
          policy_kind: change.row.policy_kind,
          policy_id: change.policyId,
          scope_type: scopeType,
          scope_id: scopeRef,
          effective_from: effectiveFrom,
          reason: reason.trim() || null,
        },
      },
    });
  }

  function finish() {
    setImpact(null);
    setPicks({});
    setReason("");
    reload();
  }

  async function handleSave() {
    const direct = changes.filter((change) => !needsImpactPreview(change.row.policy_kind));
    const previewed = changes.filter((change) => needsImpactPreview(change.row.policy_kind));
    setSaving(true);
    setSaveError(null);
    try {
      if (direct.length > 0) {
        await apiClient.post("/policy-assignments/batch", {
          scope_type: scopeType,
          scope_id: scopeRef,
          effective_from: effectiveFrom,
          reason: reason.trim() || null,
          changes: direct.map((change) => ({
            policy_kind: change.row.policy_kind,
            policy_id: change.policyId,
            leave_type_id: change.row.leave_type_id,
            expected_version: change.row.own?.version ?? null,
          })),
        });
        toast({
          title: direct.length === 1 ? "Assignment saved" : `${direct.length} assignments saved`,
          variant: "success",
        });
      }
      setReviewOpen(false);
      setPicks((current) => {
        const next = { ...current };
        for (const change of direct) delete next[coverageRowKey(change.row)];
        return next;
      });
      const [first, ...rest] = previewed;
      if (first) impactFor(first, rest);
      else finish();
    } catch (err) {
      const context = err instanceof ApiError ? err.details[0]?.context : undefined;
      const failed = direct.find(
        (change) =>
          change.row.policy_kind === (context as { policy_kind?: string } | undefined)?.policy_kind &&
          change.row.leave_type_id ===
            ((context as { leave_type_id?: string | null } | undefined)?.leave_type_id ?? null),
      );
      setSaveError(
        `Nothing was saved. ${failed ? `${coverageRowLabel(failed.row)}: ` : ""}${describeApiError(err)}`,
      );
    } finally {
      setSaving(false);
    }
  }

  const options = scopeOptions[scopeType] ?? [];
  const previewedCount = changes.filter((c) => needsImpactPreview(c.row.policy_kind)).length;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="grid grid-cols-1 gap-4 pt-6 sm:grid-cols-2">
          <FormField id="set-scope-type" label="Who does this apply to?" required>
            <NativeSelect
              value={scopeType}
              onChange={(e) => changeScope(e.target.value as ScopeType, "")}
            >
              {SCOPE_TYPES.map((scope) => (
                <option key={scope} value={scope}>
                  {SCOPE_TYPE_LABELS[scope]}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          {scopeType === "EMPLOYEE" ? (
            <FormField id="set-scope-employee" label="Employee" required>
              <EmployeeSelect
                directory={directory}
                value={scopeId}
                onChange={(id) => changeScope("EMPLOYEE", id)}
              />
            </FormField>
          ) : null}
          {scopeType !== "COMPANY" && scopeType !== "EMPLOYEE" ? (
            <FormField id="set-scope-id" label={SCOPE_TYPE_LABELS[scopeType]} required>
              <NativeSelect value={scopeId} onChange={(e) => changeScope(scopeType, e.target.value)}>
                <option value="">Choose…</option>
                {options.map((option) => (
                  <option key={option.id} value={option.id}>
                    {optionLabel(option)}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          ) : null}
        </CardContent>
      </Card>

      {!ready ? (
        <p className="rounded-lg border border-dashed border-border px-6 py-12 text-center text-sm text-foreground-secondary">
          Choose who to see what they follow.
        </p>
      ) : null}

      {ready && !coverage && !showing?.error ? (
        <div role="status" aria-label="Loading policies">
          <TableSkeleton rows={6} columns={3} />
        </div>
      ) : null}

      {ready && showing?.error ? (
        <ErrorState
          message={
            showing.error.status === 403
              ? "You do not have permission to manage policy assignments."
              : showing.error.message
          }
          onRetry={reload}
        />
      ) : null}

      {ready && coverage ? (
        <BusyRegion busy={!showing} label="Refreshing…">
          <TableContainer>
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Policy type</TableHead>
                  <TableHead>Applies today</TableHead>
                  <TableHead>Change to</TableHead>
                  <TableHead align="right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {coverage.rows.map((row) => {
                  const key = coverageRowKey(row);
                  const label = coverageRowLabel(row);
                  const startsLater = row.own && row.own.effective_from > today;
                  return (
                    <TableRow key={key}>
                      <TableCell className="font-medium text-foreground">{label}</TableCell>
                      <TableCell>
                        {row.applied ? (
                          <>
                            <p className="text-sm text-foreground">
                              {row.applied.policy_name ?? "Name unavailable"}
                            </p>
                            <p className="mt-0.5 text-xs text-foreground-muted">
                              {row.applied.scope_type === scopeType ? (
                                row.applied.effective_to ? (
                                  <>
                                    Set here until <CompanyDate value={row.applied.effective_to} />
                                    , then inherited
                                  </>
                                ) : (
                                  <>
                                    Set here since <CompanyDate value={row.applied.effective_from} />
                                  </>
                                )
                              ) : (
                                <>Inherited from {appliedSourceLabel(row.applied)}</>
                              )}
                            </p>
                            {!row.applied.has_rules ? (
                              <p className="mt-0.5 text-xs text-danger">
                                This policy has no published rules for today.
                              </p>
                            ) : null}
                          </>
                        ) : (
                          <Badge variant="outline">Not set</Badge>
                        )}
                        {startsLater && row.own ? (
                          <p className="mt-0.5 text-xs text-foreground-muted">
                            Changes to {row.own.policy_name ?? "another policy"} from{" "}
                            <CompanyDate value={row.own.effective_from} />
                          </p>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <NativeSelect
                          aria-label={`Change ${label}`}
                          value={picks[key] ?? row.own?.policy_id ?? ""}
                          onChange={(e) =>
                            setPicks((current) => ({ ...current, [key]: e.target.value }))
                          }
                        >
                          {!row.own ? (
                            <option value="">
                              {row.applied ? "Keep inherited" : "Not set"}
                            </option>
                          ) : null}
                          {rowOptions(row).map((option) => (
                            <option key={option.id} value={option.id}>
                              {optionLabel(option)}
                            </option>
                          ))}
                        </NativeSelect>
                      </TableCell>
                      <TableCell align="right">
                        {row.own && canEndAssignment(row.policy_kind, scopeType) ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              row.own &&
                              setEnding({
                                assignmentId: row.own.assignment_id,
                                version: row.own.version,
                                effectiveFrom: row.own.effective_from,
                                description: `${label}: ${row.own.policy_name ?? "this policy"}`,
                              })
                            }
                          >
                            Return to inherited
                          </Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </BusyRegion>
      ) : null}

      {ready && coverage ? (
        <Card>
          <CardContent className="grid grid-cols-1 items-end gap-4 pt-6 sm:grid-cols-[auto_minmax(0,1fr)_auto]">
            <FormField id="set-effective-from" label="Effective from" required>
              <Input
                type="date"
                value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)}
              />
            </FormField>
            <FormField id="set-reason" label="Reason (optional)">
              <Input value={reason} onChange={(e) => setReason(e.target.value)} />
            </FormField>
            <Button type="button" onClick={openReview} disabled={changes.length === 0}>
              {changes.length === 0
                ? "No changes"
                : changes.length === 1
                  ? "Review 1 change"
                  : `Review ${changes.length} changes`}
            </Button>
            {formError ? (
              <p className="text-sm text-danger sm:col-span-3">{formError}</p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <Dialog open={reviewOpen} onOpenChange={(open) => (!saving ? setReviewOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Review changes</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-foreground-secondary">
            For {SCOPE_TYPE_LABELS[scopeType]}, from{" "}
            <CompanyDate value={effectiveFrom || null} />.
          </p>
          <ul className="divide-y divide-border rounded-md border border-border">
            {changes.map((change) => (
              <li key={coverageRowKey(change.row)} className="px-3 py-2 text-sm">
                <p className="font-medium text-foreground">{coverageRowLabel(change.row)}</p>
                <p className="text-foreground-secondary">
                  {change.row.own?.policy_name ?? change.row.applied?.policy_name ?? "Not set"} →{" "}
                  {change.policyName}
                </p>
              </li>
            ))}
          </ul>
          {effectiveFrom < today ? (
            <p className="text-sm text-warning">This starts in the past.</p>
          ) : null}
          {previewedCount > 0 ? (
            <p className="text-sm text-foreground-secondary">
              Work calendar and weekly-off changes open an impact preview next, one at a time. Other
              changes are saved first, and stay saved if you cancel a preview.
            </p>
          ) : null}
          {saveError ? <p className="text-sm text-danger">{saveError}</p> : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setReviewOpen(false)}
              disabled={saving}
            >
              Back
            </Button>
            <Button type="button" onClick={() => void handleSave()} disabled={saving}>
              {saving ? "Saving…" : "Confirm"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ChangeImpactDialog
        change={impact?.change ?? null}
        title={impact?.title ?? ""}
        onClose={() => {
          setImpact(null);
          reload();
        }}
        onApplied={() => {
          const [next, ...rest] = impact?.rest ?? [];
          if (next) impactFor(next, rest);
          else finish();
        }}
      />

      {ending ? (
        <EndAssignmentDialog
          key={ending.assignmentId}
          target={ending}
          today={today}
          onClose={() => setEnding(null)}
          onEnded={() => {
            setEnding(null);
            reload();
          }}
        />
      ) : null}
    </div>
  );
}

