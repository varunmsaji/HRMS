"use client";

import { Lock } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { AttendancePeriodStatusBadge } from "@/components/attendance-period/attendance-period-status-badge";
import { FinalizePeriodDialog } from "@/components/attendance-period/finalize-period-dialog";
import { ReopenPeriodDialog } from "@/components/attendance-period/reopen-period-dialog";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import {
  ATTENDANCE_PERIOD_ACTION_LABELS,
  ATTENDANCE_PERIOD_BLOCKING_REASON_LABELS,
  ATTENDANCE_PERIOD_SUMMARY_COLUMNS as SUMMARY_COLUMNS,
  type AttendancePeriod,
  type AttendancePeriodSummaryRow,
  type AttendancePeriodValidation,
} from "@/lib/attendance-period/types";
import { formatDateTime } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { LegalEntity } from "@/lib/legal-entity/types";

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-foreground">{value}</dd>
    </div>
  );
}

/** `GET /v1/attendance-periods/{id}` detail (architecture §4.2/§22, decision log WD-30). Shows
 * lifecycle status, the append-only action timeline, on-demand finalization validation, and the
 * per-employee summary — a live, unpersisted preview while `OPEN`, the frozen payroll-facing
 * snapshot once `CLOSED` ("regenerated only while unlocked; frozen at lock/snapshot"). Backend
 * remains authoritative for every mutation; this page never re-implements the lock/finalization
 * rules, only surfaces their results. */
export default function AttendancePeriodDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const { can } = usePermissions();
  const tz = user?.company_timezone ?? "Asia/Kolkata";

  const [period, setPeriod] = useState<AttendancePeriod | null>(null);
  const [summary, setSummary] = useState<AttendancePeriodSummaryRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [validation, setValidation] = useState<AttendancePeriodValidation | null>(null);
  const [validating, setValidating] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  const [finalizeOpen, setFinalizeOpen] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);
  const [calculating, setCalculating] = useState(false);
  const [legalEntityName, setLegalEntityName] = useState<string | null>(null);
  const { toast } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [periodData, summaryData] = await Promise.all([
        apiClient.get<AttendancePeriod>(`/attendance-periods/${params.id}`),
        apiClient.get<AttendancePeriodSummaryRow[]>(`/attendance-periods/${params.id}/summary`),
      ]);
      setPeriod(periodData);
      setSummary(summaryData);
      // Display only — the period is still usable if the entity cannot be read.
      apiClient
        .get<LegalEntity>(`/legal-entities/${periodData.legal_entity_id}`)
        .then((entity) => setLegalEntityName(entity.name))
        .catch(() => setLegalEntityName(null));
    } catch (err) {
      setPeriod(null);
      setSummary(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleValidate() {
    if (!period) return;
    setValidating(true);
    setValidationError(null);
    try {
      const result = await apiClient.post<AttendancePeriodValidation>(
        `/attendance-periods/${period.id}/validate`,
        {},
      );
      setValidation(result);
    } catch (err) {
      setValidationError(describeApiError(err));
    } finally {
      setValidating(false);
    }
  }

  /** PAY-001 — queues calculation of every employed day in the period (up to today) for this
   * period's legal entity (decision 14) so it can be finalized; the job runs in the background
   * and `Validate` shows when it has caught up. */
  async function handleCalculateRange() {
    if (!period) return;
    const today = new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD, local
    const dateTo = period.period_end < today ? period.period_end : today;
    setCalculating(true);
    try {
      await apiClient.post(`/attendance/days/calculate-range`, {
        date_from: period.period_start,
        date_to: dateTo,
        legal_entity_id: period.legal_entity_id,
      });
      toast({
        title: "Attendance calculation queued",
        description: `${period.period_start} – ${dateTo}. Run Validate in a few minutes to check progress.`,
        variant: "success",
      });
    } catch (err) {
      toast({ title: "Could not queue calculation", description: describeApiError(err), variant: "danger" });
    } finally {
      setCalculating(false);
    }
  }

  const canManage = can("ATTENDANCE.LOCK");
  const canRecompute = can("ATTENDANCE.RECOMPUTE");
  const canUnlock = can("ATTENDANCE.UNLOCK");
  const isOpen = period?.status === "OPEN";
  const isClosed = period?.status === "CLOSED";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Attendance period"
        description={period ? `${period.period_start} – ${period.period_end}` : undefined}
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => router.push("/app/attendance-periods")}
            >
              Back to periods
            </Button>
            {isOpen && canRecompute ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => void handleCalculateRange()}
                disabled={calculating}
              >
                {calculating ? "Queuing…" : "Calculate attendance"}
              </Button>
            ) : null}
            {isOpen && canManage ? (
              <>
                <Button type="button" variant="outline" onClick={() => void handleValidate()} disabled={validating}>
                  {validating ? "Validating…" : "Validate"}
                </Button>
                <Button type="button" onClick={() => setFinalizeOpen(true)}>
                  Finalize & lock
                </Button>
              </>
            ) : null}
            {isClosed && canUnlock ? (
              <Button type="button" variant="destructive" onClick={() => setReopenOpen(true)}>
                Reopen
              </Button>
            ) : null}
          </div>
        }
      />

      {loading ? <LoadingState label="Loading attendance period…" fullPage /> : null}
      {error && !loading ? (
        <ErrorState
          message={
            error.status === 404
              ? "This attendance period was not found, or you don't have access to it."
              : error.message
          }
          onRetry={() => void load()}
        />
      ) : null}

      {!loading && !error && period ? (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <AttendancePeriodStatusBadge status={period.status} />
            {isClosed ? (
              <Badge variant="outline" className="gap-1">
                <Lock className="h-3 w-3" />
                Historical attendance in this range is immutable
              </Badge>
            ) : null}
          </div>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Period</h2>
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field label="Label" value={period.label ?? "—"} />
                <Field label="Legal entity" value={legalEntityName ?? "—"} />
                <Field label="Period start" value={period.period_start} />
                <Field label="Period end" value={period.period_end} />
                <Field label="Opened at" value={formatDateTime(period.opened_at, tz)} />
                <Field label="Closed at" value={formatDateTime(period.closed_at, tz)} />
                <Field label="Reopen reason" value={period.reopen_reason ?? "—"} />
              </dl>
            </CardContent>
          </Card>

          {validationError ? (
            <p role="alert" className="text-sm text-danger">
              {validationError}
            </p>
          ) : null}
          {validation ? (
            <Card>
              <CardContent className="pt-6">
                <div className="mb-4 flex items-center gap-2">
                  <h2 className="text-sm font-medium text-foreground">Finalization readiness</h2>
                  <Badge variant={validation.status === "READY" ? "success" : "warning"}>
                    {validation.status}
                  </Badge>
                </div>
                {validation.status === "BLOCKED" ? (
                  <ul className="space-y-2 text-sm">
                    {validation.reasons.map((reason) => (
                      <li key={reason.code} className="rounded-md border border-border p-3">
                        <p className="font-medium text-foreground">
                          {ATTENDANCE_PERIOD_BLOCKING_REASON_LABELS[reason.code] ?? reason.code}
                          {" — "}
                          {reason.count}
                        </p>
                        <p className="text-foreground-secondary">{reason.message}</p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-foreground-secondary">
                    Every check passed — this period can be finalized.
                  </p>
                )}
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">
                Summary {summary && summary.length > 0 && summary[0]?.frozen ? "(frozen)" : "(live preview)"}
              </h2>
              {summary && summary.length === 0 ? (
                <p className="text-sm text-foreground-secondary">
                  No calculated attendance in this range yet.
                </p>
              ) : null}
              {summary && summary.length > 0 ? (
                <div className="overflow-x-auto rounded-md border border-border">
                  <table className="w-full text-sm">
                    <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">Employee</th>
                        {SUMMARY_COLUMNS.map((column) => (
                          <th key={column.key} className="px-3 py-2 text-right font-medium">
                            {column.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {summary.map((row) => (
                        <tr key={row.employee_id}>
                          <td className="px-3 py-2 font-medium text-foreground">{row.employee_id}</td>
                          {SUMMARY_COLUMNS.map((column) => (
                            <td
                              key={column.key}
                              className="px-3 py-2 text-right text-foreground-secondary"
                            >
                              {row[column.key] ?? "—"}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Timeline</h2>
              <ol className="space-y-3">
                {period.actions.map((entry) => (
                  <li key={entry.id} className="flex items-start justify-between gap-4 text-sm">
                    <div>
                      <p className="font-medium text-foreground">
                        {ATTENDANCE_PERIOD_ACTION_LABELS[entry.action] ?? entry.action}
                      </p>
                      {entry.comment ? (
                        <p className="text-foreground-secondary">{entry.comment}</p>
                      ) : null}
                    </div>
                    <span className="whitespace-nowrap text-xs text-foreground-muted">
                      {formatDateTime(entry.created_at, tz)}
                    </span>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        </div>
      ) : null}

      <FinalizePeriodDialog
        open={finalizeOpen}
        onOpenChange={setFinalizeOpen}
        period={period}
        onDone={(updated) => {
          setPeriod(updated);
          void load();
        }}
      />
      <ReopenPeriodDialog
        open={reopenOpen}
        onOpenChange={setReopenOpen}
        period={period}
        onDone={(updated) => {
          setPeriod(updated);
          void load();
        }}
      />
    </div>
  );
}
