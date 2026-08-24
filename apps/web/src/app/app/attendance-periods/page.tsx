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
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { AttendancePeriod } from "@/lib/attendance-period/types";

/** `/v1/attendance-periods` list (architecture §4.2/§22, decision log WD-30). Company-wide
 * config/administration screen, not employee-scoped — mirrors the Attendance/Overtime/
 * Regularization Policies screens' single unfiltered list rather than a My/Team toggle. */
export default function AttendancePeriodsPage() {
  const { can } = usePermissions();
  const canManage = can("ATTENDANCE.LOCK");

  const [periods, setPeriods] = useState<AttendancePeriod[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<AttendancePeriod[]>("/attendance-periods");
      setPeriods(data);
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

  return (
    <div className="space-y-6">
      <PageHeader
        title="Attendance Periods"
        description="Close and lock attendance for a date range once every exception in it is resolved."
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
          {!loading && !error && periods && periods.length > 0 ? (
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Label</th>
                    <th className="px-3 py-2 text-left font-medium">Range</th>
                    <th className="px-3 py-2 text-left font-medium">Status</th>
                    <th className="px-3 py-2 text-left font-medium">Last validation</th>
                    <th className="px-3 py-2 text-right font-medium">Detail</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {periods.map((period) => (
                    <tr key={period.id} className="hover:bg-accent">
                      <td className="px-3 py-2 font-medium text-foreground">
                        {period.label ?? "—"}
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
      />
    </div>
  );
}
