"use client";

import { Search, UserPlus, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmployeeIdentityCell } from "@/components/employee/employee-identity";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { BusyRegion } from "@/components/common/busy-region";
import { PageHeader } from "@/components/common/page-header";
import { PaginationControls } from "@/components/common/pagination-controls";
import { useToast } from "@/components/common/toast";
import { OnboardingCaseForm } from "@/components/onboarding/onboarding-case-form";
import { OnboardingStatusBadge } from "@/components/onboarding/onboarding-status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
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
  TableToolbar,
} from "@/components/ui/table";
import { TableSkeleton } from "@/components/ui/skeleton";
import { isAbortError, useLatestRequest } from "@/hooks/use-latest-request";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
import { initialQueryValue } from "@/lib/dashboard/overview";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import {
  ONBOARDING_CASE_STATUS_VALUES,
  type OnboardingCase,
  type OnboardingCaseStatus,
} from "@/lib/onboarding/types";
import {
  EMPTY_ONBOARDING_CASE_FORM_VALUES,
  buildCreatePayload,
  validateOnboardingCaseForm,
  type OnboardingCaseFormErrors,
  type OnboardingCaseFormValues,
} from "@/lib/onboarding/validate-onboarding";

interface ReferenceData {
  branches: Branch[];
  departments: Department[];
  designations: Designation[];
}

function candidateName(onboardingCase: OnboardingCase): string {
  return [onboardingCase.candidate_first_name, onboardingCase.candidate_last_name]
    .filter(Boolean)
    .join(" ");
}

/** Reference lists (branches, departments…) are best-effort: a failure leaves them empty, but a
 * cancellation must still propagate so an obsolete load is dropped, not half-applied. */
function swallowExceptAbort(error: unknown): never[] {
  if (isAbortError(error)) throw error;
  return [];
}

export default function OnboardingPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const router = useRouter();
  const [cases, setCases] = useState<OnboardingCase[] | null>(null);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [page, setPage] = useState(1);
  const [refs, setRefs] = useState<ReferenceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<OnboardingCaseStatus | "">(() =>
    initialQueryValue("status", ONBOARDING_CASE_STATUS_VALUES),
  );

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<OnboardingCaseFormValues>(
    EMPTY_ONBOARDING_CASE_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<OnboardingCaseFormErrors>({});
  const [saving, setSaving] = useState(false);

  const beginRequest = useLatestRequest();

  const load = useCallback(
    async (targetPage: number, targetStatus: OnboardingCaseStatus | "") => {
      const request = beginRequest();
      setLoading(true);
      setError(null);
      try {
        // GET /v1/onboarding-cases supports server-side `status` filtering and bounded pagination.
        const [{ data, pagination: meta }, branches, departments, designations] = await Promise.all(
          [
            apiClient.getList<OnboardingCase>(
              "/onboarding-cases",
              { page: targetPage, status: targetStatus || undefined },
              { signal: request.signal },
            ),
            apiClient.get<Branch[]>("/branches", { signal: request.signal }).catch(swallowExceptAbort),
            apiClient.get<Department[]>("/departments", { signal: request.signal }).catch(swallowExceptAbort),
            apiClient.get<Designation[]>("/designations", { signal: request.signal }).catch(swallowExceptAbort),
          ],
        );
        if (!request.isCurrent()) return;
        setCases(data);
        setPagination(meta);
        setRefs({ branches, departments, designations });
      } catch (err) {
        if (isAbortError(err) || !request.isCurrent()) return;
        setCases(null);
        setPagination(null);
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
        if (request.isCurrent()) setLoading(false);
      }
    },
    [beginRequest],
  );

  useEffect(() => {
    void load(page, statusFilter);
  }, [load, page, statusFilter]);

  const filteredCases = useMemo(() => {
    if (!cases) return null;
    const q = searchQuery.trim().toLowerCase();
    if (!q) return cases;
    return cases.filter((c) => {
      const name = candidateName(c).toLowerCase();
      const email = (c.personal_email ?? "").toLowerCase();
      return name.includes(q) || email.includes(q);
    });
  }, [cases, searchQuery]);

  function openCreate() {
    setFormValues(EMPTY_ONBOARDING_CASE_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateOnboardingCaseForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    setSaving(true);
    setFormErrors({});
    try {
      const created = await apiClient.post<OnboardingCase>(
        "/onboarding-cases",
        buildCreatePayload(formValues),
      );
      setCreateOpen(false);
      toast({
        title: "Onboarding case created",
        description: `Review the invitation for ${created.candidate_first_name}; nothing is sent until you confirm.`,
        variant: "success",
      });
      router.push(`/app/onboarding/${created.id}?compose=1`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({
          candidateFirstName: getFieldError(err.details, "candidate_first_name"),
          personalEmail: getFieldError(err.details, "personal_email"),
          proposedJoiningDate: getFieldError(err.details, "proposed_joining_date"),
          designationId: getFieldError(err.details, "designation_id"),
          departmentId: getFieldError(err.details, "department_id"),
          branchId: getFieldError(err.details, "branch_id"),
        });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to start onboarding", variant: "danger" });
        return;
      }
      if (
        err instanceof ApiError &&
        err.status === 409 &&
        err.code === "DUPLICATE_ACTIVE_ONBOARDING_CASE"
      ) {
        setFormErrors({
          personalEmail: "An active onboarding case already exists for this email.",
        });
        return;
      }
      toast({
        title: "Could not start onboarding",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  const canCreate = can("ONBOARDING.CREATE");
  const totalCount = pagination?.total ?? cases?.length ?? 0;
  const showToolbar = Boolean(
    !error && cases && (cases.length > 0 || statusFilter !== ""),
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Onboarding"
        description="Start onboarding for a known new hire; they fill in their own details, you review and activate."
        badge={
          !error && cases ? (
            <Badge variant="secondary" className="tabular-nums">
              {totalCount} {totalCount === 1 ? "case" : "cases"}
            </Badge>
          ) : undefined
        }
        actions={
          showToolbar && canCreate ? (
            <Button type="button" onClick={openCreate}>
              <UserPlus className="h-4 w-4" aria-hidden="true" />
              Start Onboarding
            </Button>
          ) : null
        }
      />

      <TableContainer>
        {showToolbar ? (
          <TableToolbar>
            <div className="relative w-full max-w-xs">
              <Search
                className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-foreground-muted"
                aria-hidden="true"
              />
              <Input
                type="search"
                aria-label="Filter current page"
                placeholder="Filter current page…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-8"
              />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <NativeSelect
                aria-label="Filter by case status"
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value as OnboardingCaseStatus | "");
                  setPage(1);
                }}
                className="w-48"
              >
                <option value="">All statuses</option>
                {ONBOARDING_CASE_STATUS_VALUES.map((status) => (
                  <option key={status} value={status}>
                    {status.replaceAll("_", " ")}
                  </option>
                ))}
              </NativeSelect>

              {searchQuery || statusFilter ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setSearchQuery("");
                    setStatusFilter("");
                    setPage(1);
                  }}
                >
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                  Clear
                </Button>
              ) : null}
            </div>
          </TableToolbar>
        ) : null}

        {loading && cases === null ? (
          <div role="status" aria-label="Loading onboarding cases">
            <TableSkeleton rows={8} columns={6} />
            <span className="sr-only">Loading onboarding cases…</span>
          </div>
        ) : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view onboarding cases."
                  : error.message
              }
              onRetry={() => void load(page, statusFilter)}
            />
          </div>
        ) : null}

        {!error && cases && cases.length === 0 && !statusFilter ? (
          <div className="p-6">
            <EmptyState
              icon={UserPlus}
              title="No onboarding cases yet."
              description="Start onboarding for a new hire to send them a secure link where they fill in their own personal, address, bank, and statutory details for you to review."
              action={
                canCreate ? (
                  <Button type="button" onClick={openCreate}>
                    Start Onboarding
                  </Button>
                ) : undefined
              }
            />
          </div>
        ) : null}

        {!error && cases && cases.length === 0 && statusFilter ? (
          <div className="p-6">
            <EmptyState
              icon={Search}
              title="No onboarding cases match this status."
              description="Try clearing the status filter."
              action={
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setStatusFilter("");
                    setPage(1);
                  }}
                >
                  Clear status filter
                </Button>
              }
            />
          </div>
        ) : null}

        {!error && cases && cases.length > 0 && filteredCases ? (
          filteredCases.length === 0 ? (
            <div className="p-6">
              <EmptyState
                icon={Search}
                title="No cases on this page match your filter."
                description="Try clearing the text filter or navigating to another page."
              />
            </div>
          ) : (
            <BusyRegion busy={loading} label="Refreshing onboarding cases…">
<Table className="min-w-[640px]">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Candidate</TableHead>
                  <TableHead>Personal email</TableHead>
                  <TableHead>Proposed joining date</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead align="right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredCases.map((onboardingCase) => (
                  <TableRow key={onboardingCase.id}>
                    <TableCell>
                      <EmployeeIdentityCell
                        name={candidateName(onboardingCase) || "—"}
                        href={`/app/onboarding/${onboardingCase.id}`}
                      />
                    </TableCell>
                    <TableCell className="text-foreground-secondary">
                      {onboardingCase.personal_email}
                    </TableCell>
                    <TableCell className="tabular-nums text-foreground-secondary">
                      <CompanyDate value={onboardingCase.proposed_joining_date} />
                    </TableCell>
                    <TableCell>
                      <OnboardingStatusBadge status={onboardingCase.status} />
                    </TableCell>
                    <TableCell align="right">
                      <Link
                        href={`/app/onboarding/${onboardingCase.id}`}
                        className="text-xs font-medium text-primary hover:underline"
                      >
                        Review case
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
</BusyRegion>
          )
        ) : null}

        {pagination ? (
          <PaginationControls
            pagination={pagination}
            onPageChange={setPage}
            disabled={loading}
          />
        ) : null}
      </TableContainer>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Start Onboarding</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <OnboardingCaseForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
              branches={refs?.branches ?? []}
              departments={refs?.departments ?? []}
              designations={refs?.designations ?? []}
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
              {saving ? "Starting…" : "Start onboarding"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
