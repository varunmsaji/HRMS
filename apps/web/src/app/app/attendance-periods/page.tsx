"use client";

import { Lock, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { AttendancePeriodStatusBadge } from "@/components/attendance-period/attendance-period-status-badge";
import { CreatePeriodDialog } from "@/components/attendance-period/create-period-dialog";
import { Button } from "@/components/ui/button";
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
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { AttendancePeriod } from "@/lib/attendance-period/types";
import type { LegalEntity } from "@/lib/legal-entity/types";

/** `/v1/attendance-periods` list (architecture §4.2/§22, decision log WD-30). Company-wide
 * config/administration screen, not employee-scoped — mirrors the Attendance/Overtime/
 * Regularization Policies screens' single list rather than a My/Team toggle. Periods are per
 * company (decision 14), so the list shows and filters by entity. */
export default function AttendancePeriodsPage() {
  const { can } = usePermissions();
  const canManage = can("ATTENDANCE.LOCK");

  const [periods, setPeriods] = useState<AttendancePeriod[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [legalEntities, setLegalEntities] = useState<LegalEntity[]>([]);
  const [entityFilter, setEntityFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, entities] = await Promise.all([
        apiClient.get<AttendancePeriod[]>("/attendance-periods"),
        apiClient.get<LegalEntity[]>("/legal-entities").catch(() => [] as LegalEntity[]),
      ]);
      setPeriods(data);
      setLegalEntities(entities);
    } catch (err) {
      setPeriods(null);
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

  const entityName = (id: string) => legalEntities.find((e) => e.id === id)?.name ?? "—";
  const visiblePeriods = periods?.filter(
    (period) => !entityFilter || period.legal_entity_id === entityFilter,
  );

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title="Attendance Periods"
        description="Close and lock each company's attendance for a month once every exception in it is resolved."
        actions={
          canManage ? (
            <Button type="button" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              New period
            </Button>
          ) : undefined
        }
      />

      <TableContainer>
        {legalEntities.length > 1 ? (
          <TableToolbar>
            <div className="w-full max-w-xs">
              <NativeSelect
                aria-label="Filter by company"
                value={entityFilter}
                onChange={(e) => setEntityFilter(e.target.value)}
              >
                <option value="">All companies</option>
                {legalEntities.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
          </TableToolbar>
        ) : null}
        {loading ? <LoadingState label="Loading attendance periods…" /> : null}
        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view attendance periods."
                  : error.message
              }
              onRetry={() => void load()}
            />
          </div>
        ) : null}
        {!loading && !error && periods && periods.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={Lock}
              title="No attendance periods yet."
              description="Create one to start closing and locking a date range of attendance."
            />
          </div>
        ) : null}
        {!loading && !error && visiblePeriods && visiblePeriods.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Label</TableHead>
                <TableHead>Company</TableHead>
                <TableHead>Range</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Last validation</TableHead>
                <TableHead align="right">Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visiblePeriods.map((period) => (
                <TableRow key={period.id}>
                  <TableCell className="font-medium text-foreground">
                    {period.label ?? "—"}
                  </TableCell>
                  <TableCell className="text-foreground-secondary">
                    {entityName(period.legal_entity_id)}
                  </TableCell>
                  <TableCell className="tabular-nums text-foreground-secondary">
                    <CompanyDate value={period.period_start} /> –{" "}
                    <CompanyDate value={period.period_end} />
                  </TableCell>
                  <TableCell>
                    <AttendancePeriodStatusBadge status={period.status} />
                  </TableCell>
                  <TableCell className="text-xs text-foreground-secondary">
                    {period.last_validation_status ?? "—"}
                  </TableCell>
                  <TableCell align="right">
                    <Link
                      href={`/app/attendance-periods/${period.id}`}
                      className="text-xs font-medium text-primary hover:underline"
                    >
                      View
                    </Link>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </TableContainer>

      <CreatePeriodDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={() => void load()}
        legalEntities={legalEntities}
      />
    </div>
  );
}
