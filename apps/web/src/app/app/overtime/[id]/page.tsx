"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { OvertimeReviewDialog } from "@/components/overtime/overtime-review-dialog";
import { OvertimeStatusBadge } from "@/components/overtime/overtime-status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { formatDateTime, formatMinutes } from "@/lib/attendance/format";
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  OVERTIME_APPROVAL_CHAIN_LABELS,
  OVERTIME_DAY_CLASS_LABELS,
  type OvertimeRecord,
} from "@/lib/overtime/types";

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-foreground">{value}</dd>
    </div>
  );
}

const ACTION_LABELS: Record<string, string> = {
  DETECTED: "Overtime detected",
  APPROVER_UNRESOLVED: "No manager resolved — routed to HR",
  AUTO_APPROVED: "Auto-approved by policy",
  STAGE_APPROVED: "Approved by manager, forwarded to HR",
  APPROVED: "Approved",
  REJECTED: "Rejected",
};

/** `GET /v1/overtime/{id}` detail (architecture §13/§14). Shows the system-detected record and
 * its append-only action timeline (`OvertimeAction` — the per-stage history a single
 * `reviewed_at`/`reviewed_by_user_id` pair on the parent can't hold for `MANAGER_THEN_HR`).
 * There is no edit or cancel here — the only actions are approve and reject, and only while the
 * record is still `PENDING`. */
export default function OvertimeDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const tz = user?.company_timezone ?? "Asia/Kolkata";
  const datePattern = useCompanyDatePattern();
  const { can } = usePermissions();

  const [record, setRecord] = useState<OvertimeRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [reviewAction, setReviewAction] = useState<"approve" | "reject" | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<OvertimeRecord>(`/overtime/${params.id}`);
      setRecord(data);
    } catch (err) {
      setRecord(null);
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

  const canApprove = can("ATTENDANCE.OVERTIME_APPROVE");
  const isPending = record?.status === "PENDING";
  const isOwnRecord = Boolean(user?.employee_id && record?.employee_id === user.employee_id);
  const canReview = canApprove && isPending && !isOwnRecord;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Overtime record"
        description={
          record ? formatCompanyDate(record.attendance_date, datePattern) : undefined
        }
        actions={
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" onClick={() => router.push("/app/overtime")}>
              Back to overtime
            </Button>
            {canReview ? (
              <>
                <Button type="button" variant="outline" onClick={() => setReviewAction("reject")}>
                  Reject
                </Button>
                <Button type="button" onClick={() => setReviewAction("approve")}>
                  Approve
                </Button>
              </>
            ) : null}
          </div>
        }
      />

      {loading ? <LoadingState label="Loading overtime record…" fullPage /> : null}
      {error && !loading ? (
        <ErrorState
          message={
            error.status === 404
              ? "This overtime record was not found, or you don't have access to it."
              : error.message
          }
          onRetry={() => void load()}
        />
      ) : null}

      {!loading && !error && record ? (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <OvertimeStatusBadge status={record.status} />
            {record.approval_stage ? (
              <Badge variant="outline">Pending {record.approval_stage.toLowerCase()} review</Badge>
            ) : null}
          </div>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Record</h2>
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field
                  label="Attendance date"
                  value={formatCompanyDate(record.attendance_date, datePattern)}
                />
                <Field
                  label="Day class"
                  value={record.day_class ? OVERTIME_DAY_CLASS_LABELS[record.day_class] : "—"}
                />
                <Field
                  label="Rate"
                  value={
                    record.classification_code
                      ? `${record.classification_code}${
                          record.configured_multiplier ? ` (${record.configured_multiplier}x)` : ""
                        }`
                      : "—"
                  }
                />
                <Field label="Minutes detected" value={formatMinutes(record.minutes_detected)} />
                <Field label="Minutes approved" value={formatMinutes(record.minutes_approved)} />
                <Field label="Approval chain" value={OVERTIME_APPROVAL_CHAIN_LABELS[record.approval_chain]} />
                <Field label="Approval stage" value={record.approval_stage ?? "—"} />
                {record.comp_off_minutes > 0 ? (
                  <Field
                    label="Comp-off"
                    value={
                      <>
                        {formatMinutes(record.comp_off_minutes)}
                        {record.comp_off_expiry_date
                          ? `, expires ${formatCompanyDate(record.comp_off_expiry_date, datePattern)}`
                          : ""}
                      </>
                    }
                  />
                ) : null}
                <Field
                  label="Attendance day"
                  value={
                    <a
                      href={`/app/attendance/${record.attendance_day_id}`}
                      className="text-primary hover:underline"
                    >
                      View attendance day
                    </a>
                  }
                />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Review</h2>
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field label="Reviewed at" value={formatDateTime(record.reviewed_at, tz)} />
                <Field label="Reviewer comment" value={record.reviewer_comment ?? "—"} />
                <Field label="Rejection reason" value={record.rejection_reason ?? "—"} />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Timeline</h2>
              <ol className="space-y-3">
                {record.actions.map((entry) => (
                  <li key={entry.id} className="flex items-start justify-between gap-4 text-sm">
                    <div>
                      <p className="font-medium text-foreground">
                        {ACTION_LABELS[entry.action] ?? entry.action}
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

      <OvertimeReviewDialog
        open={reviewAction !== null}
        onOpenChange={(open) => !open && setReviewAction(null)}
        record={record}
        action={reviewAction ?? "approve"}
        onDone={(updated) => setRecord(updated)}
      />
    </div>
  );
}
