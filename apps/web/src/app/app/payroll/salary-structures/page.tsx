"use client";

import { LayoutList, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  currentVersion,
  draftVersion,
  type EmployeeSalaryBulkResult,
  type SalaryStructure,
} from "@/lib/payroll/types";

/** Payroll Phase 5.1 — salary structures (`/v1/payroll/salary-structures`). `Standard` and
 * `Standard (metro)` are seeded automatically (D1: Basic 50 % of gross, HRA 40 %/50 % of Basic,
 * Special Allowance as the balance). "Assign to employees" gives every monthly-paid employee
 * without a structure one, so existing staff can reach their first pay run. */
export default function SalaryStructuresPage() {
  const router = useRouter();
  const { toast } = useToast();
  const { user } = useAuth();
  const { can } = usePermissions();
  const canManage = can("PAYROLL.SETUP_MANAGE");

  const [structures, setStructures] = useState<SalaryStructure[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [codeError, setCodeError] = useState<string | undefined>();
  const [saving, setSaving] = useState(false);

  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkStructureId, setBulkStructureId] = useState("");
  const [bulkDate, setBulkDate] = useState(() =>
    businessToday(user?.company_timezone ?? "Asia/Kolkata"),
  );
  const [bulkResult, setBulkResult] = useState<EmployeeSalaryBulkResult | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStructures(await apiClient.get<SalaryStructure[]>("/payroll/salary-structures"));
    } catch (err) {
      setStructures(null);
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

  async function handleCreate() {
    setSaving(true);
    setCodeError(undefined);
    try {
      const created = await apiClient.post<SalaryStructure>("/payroll/salary-structures", {
        code: code.trim().toUpperCase(),
        name: name.trim(),
      });
      setCreateOpen(false);
      router.push(`/app/payroll/salary-structures/${created.id}`);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 409 || err.status === 422)) {
        setCodeError(
          getFieldError(err.details, "code") ??
            getFieldError(err.details, "body.code") ??
            err.message,
        );
        return;
      }
      toast({
        title: "Could not create structure",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleBulkAssign() {
    setSaving(true);
    try {
      const result = await apiClient.post<EmployeeSalaryBulkResult>(
        "/payroll/salary-assignments/bulk",
        { salary_structure_id: bulkStructureId, effective_from: bulkDate },
      );
      setBulkResult(result);
    } catch (err) {
      toast({
        title: "Could not assign structure",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  const published = structures?.filter((s) => s.is_active && currentVersion(s)) ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title="Salary Structures"
        description="How an employee's CTC splits into salary components."
        actions={
          canManage ? (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setBulkResult(null);
                  setBulkStructureId(published[0]?.id ?? "");
                  setBulkOpen(true);
                }}
                disabled={published.length === 0}
              >
                Assign to employees
              </Button>
              <Button type="button" onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4" aria-hidden="true" />
                New structure
              </Button>
            </div>
          ) : undefined
        }
      />

      <TableContainer>
        {loading ? <LoadingState label="Loading salary structures…" /> : null}
        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to manage payroll setup."
                  : error.message
              }
              onRetry={() => void load()}
            />
          </div>
        ) : null}
        {!loading && !error && structures && structures.length === 0 ? (
          <div className="p-6">
            <EmptyState icon={LayoutList} title="No salary structures yet." />
          </div>
        ) : null}
        {!loading && !error && structures && structures.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Structure</TableHead>
                <TableHead>In effect since</TableHead>
                <TableHead>Status</TableHead>
                <TableHead align="right">Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {structures.map((structure) => {
                const current = currentVersion(structure);
                const draft = draftVersion(structure);
                return (
                  <TableRow key={structure.id}>
                    <TableCell>
                      <Link
                        href={`/app/payroll/salary-structures/${structure.id}`}
                        className="font-medium text-foreground hover:text-primary hover:underline"
                      >
                        {structure.name}
                      </Link>
                      <div className="text-xs text-foreground-muted">
                        <span className="font-mono">{structure.code}</span>
                        {structure.description ? ` · ${structure.description}` : ""}
                      </div>
                    </TableCell>
                    <TableCell className="tabular-nums text-foreground-secondary">
                      {current?.effective_from ? (
                        <CompanyDate value={current.effective_from} />
                      ) : (
                        "Not published"
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {!structure.is_active ? <Badge variant="outline">Inactive</Badge> : null}
                        {draft ? <Badge variant="warning">Draft pending</Badge> : null}
                        {structure.is_active && current && !draft ? (
                          <Badge variant="success" dot>
                            Published
                          </Badge>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell align="right">
                      <Link
                        href={`/app/payroll/salary-structures/${structure.id}`}
                        className="text-xs font-medium text-primary hover:underline"
                      >
                        View
                      </Link>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        ) : null}
      </TableContainer>

      <Dialog open={createOpen} onOpenChange={(next) => !saving && setCreateOpen(next)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>New salary structure</DialogTitle>
            <DialogDescription>
              It starts as a draft — add its components, preview a CTC, then publish it.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <FormField
              id="structure-code"
              label="Code"
              required
              error={codeError}
              description="Capital letters, digits and underscores, e.g. SALES."
            >
              <Input value={code} maxLength={30} onChange={(e) => setCode(e.target.value)} />
            </FormField>
            <FormField id="structure-name" label="Name" required>
              <Input value={name} maxLength={150} onChange={(e) => setName(e.target.value)} />
            </FormField>
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
              disabled={saving || !code.trim() || !name.trim()}
            >
              {saving ? "Creating…" : "Create structure"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={bulkOpen} onOpenChange={(next) => !saving && setBulkOpen(next)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Assign a structure to employees</DialogTitle>
            <DialogDescription>
              Every monthly-paid employee employed on this date who has no salary structure yet
              gets this one. Daily-wage employees and anyone without a CTC are listed as skipped.
            </DialogDescription>
          </DialogHeader>
          {bulkResult ? (
            <div className="space-y-3 text-sm">
              <p className="text-foreground">
                Assigned {bulkResult.assigned.length} employee
                {bulkResult.assigned.length === 1 ? "" : "s"}; skipped {bulkResult.skipped.length}.
              </p>
              {bulkResult.skipped.length > 0 ? (
                <ul className="max-h-60 space-y-1 overflow-y-auto rounded-md border border-border p-2">
                  {bulkResult.skipped.map((skip) => (
                    <li key={skip.employee_id}>
                      <Link
                        href={`/app/employees/${skip.employee_id}`}
                        className="text-primary hover:underline"
                      >
                        Employee
                      </Link>{" "}
                      — {skip.reason}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : (
            <div className="space-y-4">
              <FormField id="bulk-structure" label="Structure">
                <NativeSelect
                  value={bulkStructureId}
                  onChange={(e) => setBulkStructureId(e.target.value)}
                >
                  {published.map((structure) => (
                    <option key={structure.id} value={structure.id}>
                      {structure.name}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
              <FormField id="bulk-date" label="Effective from">
                <Input
                  type="date"
                  value={bulkDate}
                  onChange={(e) => setBulkDate(e.target.value)}
                />
              </FormField>
            </div>
          )}
          <DialogFooter>
            {bulkResult ? (
              <Button type="button" onClick={() => setBulkOpen(false)}>
                Done
              </Button>
            ) : (
              <>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setBulkOpen(false)}
                  disabled={saving}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  onClick={() => void handleBulkAssign()}
                  disabled={saving || !bulkStructureId || !bulkDate}
                >
                  {saving ? "Assigning…" : "Assign"}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
