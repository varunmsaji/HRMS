"use client";

import { Lock } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { AttendancePeriodStatusBadge } from "@/components/attendance-period/attendance-period-status-badge";
import { CreatePeriodDialog } from "@/components/attendance-period/create-period-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { AttendancePeriod } from "@/lib/attendance-period/types";
import type { LegalEntity } from "@/lib/legal-entity/types";

/** `/v1/attendance-periods` list (architecture §4.2/§22, decision log WD-30). Company-wide
 * config/administration screen, not employee-scoped — mirrors the Attendance/Overtime/
 * Regularization Policies screens' single list rather than a My/Team toggle. Periods are per
 * legal entity (decision 14), so the list shows and filters by entity. */
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
      // Entity names are a nicety — a caller who cannot read legal entities still gets the list.
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
        title="Attendance Periods"
        description="Close and lock each legal entity's attendance for a month once every exception in it is resolved."
        actions={
          canManage ? (
            <Button type="button" onClick={() => setCreateOpen(true)}>
              New period
            </Button>
          ) : undefined
        }
      />

      <Card>
        <CardContent className="pt-6">
          {legalEntities.length > 1 ? (
            <div className="mb-4 max-w-xs">
              <NativeSelect
                aria-label="Filter by legal entity"
                value={entityFilter}
                onChange={(e) => setEntityFilter(e.target.value)}
              >
                <option value="">All legal entities</option>
                {legalEntities.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
          ) : null}
          {loading ? <LoadingState label="Loading attendance periods…" /> : null}
          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view attendance periods."
                  : error.message
              }
              onRetry={() => void load()}
            />
          ) : null}
          {!loading && !error && periods && periods.length === 0 ? (
            <EmptyState
              icon={Lock}
              title="No attendance periods yet."
              description="Create one to start closing and locking a date range of attendance."
            />
          ) : null}
          {!loading && !error && visiblePeriods && visiblePeriods.length > 0 ? (
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Label</th>
                    <th className="px-3 py-2 text-left font-medium">Legal entity</th>
                    <th className="px-3 py-2 text-left font-medium">Range</th>
                    <th className="px-3 py-2 text-left font-medium">Status</th>
                    <th className="px-3 py-2 text-left font-medium">Last validation</th>
                    <th className="px-3 py-2 text-right font-medium">Detail</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {visiblePeriods.map((period) => (
                    <tr key={period.id} className="hover:bg-accent">
                      <td className="px-3 py-2 font-medium text-foreground">
                        {period.label ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-foreground-secondary">
                        {entityName(period.legal_entity_id)}
                      </td>
                      <td className="px-3 py-2 text-foreground-secondary">
                        {period.period_start} – {period.period_end}
                      </td>
                      <td className="px-3 py-2">
                        <AttendancePeriodStatusBadge status={period.status} />
                      </td>
                      <td className="px-3 py-2 text-foreground-secondary">
                        {period.last_validation_status ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Link
                          href={`/app/attendance-periods/${period.id}`}
                          className="text-sm font-medium text-primary hover:underline"
                        >
                          View
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <CreatePeriodDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={() => void load()}
        legalEntities={legalEntities}
      />
    </div>
  );
}
