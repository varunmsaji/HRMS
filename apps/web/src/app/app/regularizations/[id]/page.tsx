"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { RegularizationReviewDialog } from "@/components/regularization/regularization-review-dialog";
import { RegularizationStatusBadge } from "@/components/regularization/regularization-status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import { REGULARIZATION_TYPE_LABELS, type RegularizationRequest } from "@/lib/regularization/types";

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-foreground">{value}</dd>
    </div>
  );
}

const ACTION_LABELS: Record<string, string> = {
  SUBMITTED: "Submitted",
  APPROVER_UNRESOLVED: "No manager resolved — routed to HR",
  STAGE_APPROVED: "Approved by manager, forwarded to HR",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  CANCELLED: "Cancelled",
  APPLIED: "Correction applied to attendance",
};

/** `GET /v1/regularizations/{id}` detail (architecture §13/§14, WD-28). Shows the original
 * request, its requested punch/shift correction, and the append-only action timeline
 * (`AttendanceRegularizationAction` — the per-stage history a single `reviewed_at`/
 * `reviewed_by_user_id` pair on the parent can't hold for `MANAGER_THEN_HR`). */
export default function RegularizationDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { toast } = useToast();
  const { user } = useAuth();
  const { can } = usePermissions();

  const [request, setRequest] = useState<RegularizationRequest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [reviewAction, setReviewAction] = useState<"approve" | "reject" | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<RegularizationRequest>(`/regularizations/${params.id}`);
      setRequest(data);
    } catch (err) {
      setRequest(null);
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

  async function handleCancel() {
    if (!request) return;
    setCancelling(true);
    try {
      const updated = await apiClient.post<RegularizationRequest>(
        `/regularizations/${request.id}/cancel`,
        {},
        { ifMatch: String(request.version) },
      );
      setRequest(updated);
      setCancelOpen(false);
      toast({ title: "Request cancelled", variant: "success" });
    } catch (err) {
      toast({ title: "Could not cancel", description: describeApiError(err), variant: "danger" });
    } finally {
      setCancelling(false);
    }
  }

  const canApprove = can("ATTENDANCE.REGULARIZATION_APPROVE");
  const isPending = request?.status === "SUBMITTED" && request.approval_stage !== null;
  const isOwnRequest = Boolean(user?.employee_id && request?.employee_id === user.employee_id);
  const canReview = canApprove && isPending && !isOwnRequest;
  const canCancel = request?.status === "SUBMITTED" && request.submitted_by_user_id === user?.id;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Regularization request"
        description={
          request
            ? `${request.attendance_date} — ${REGULARIZATION_TYPE_LABELS[request.request_type]}`
            : undefined
        }
        actions={
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" onClick={() => router.push("/app/regularizations")}>
              Back to regularizations
            </Button>
            {canCancel ? (
              <Button type="button" variant="outline" onClick={() => setCancelOpen(true)}>
                Cancel request
              </Button>
            ) : null}
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

      {loading ? <LoadingState label="Loading regularization request…" fullPage /> : null}
      {error && !loading ? (
        <ErrorState
          message={
            error.status === 404
              ? "This request was not found, or you don't have access to it."
              : error.message
          }
          onRetry={() => void load()}
        />
      ) : null}

      {!loading && !error && request ? (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <RegularizationStatusBadge status={request.status} />
            {request.approval_stage ? (
              <Badge variant="outline">Pending {request.approval_stage.toLowerCase()} review</Badge>
            ) : null}
          </div>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Request</h2>
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field label="Attendance date" value={request.attendance_date} />
                <Field label="Request type" value={REGULARIZATION_TYPE_LABELS[request.request_type]} />
                <Field label="Reason" value={request.reason ?? "—"} />
                <Field label="Attachment reference" value={request.attachment_reference ?? "—"} />
                <Field label="Approval chain" value={request.approval_chain} />
                <Field label="Approval stage" value={request.approval_stage ?? "—"} />
                <Field label="Submitted at" value={formatDateTime(request.submitted_at)} />
                <Field
                  label="Attendance day"
                  value={
                    request.attendance_day_id ? (
                      <a
                        href={`/app/attendance/${request.attendance_day_id}`}
                        className="text-primary hover:underline"
                      >
                        View attendance day
                      </a>
                    ) : (
                      "Not yet calculated"
                    )
                  }
                />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Requested correction</h2>
              {request.requested_shift_id ? (
                <p className="text-sm text-foreground-secondary">
                  Correct shift: <span className="font-medium">{request.requested_shift_id}</span>
                </p>
              ) : null}
              {request.requested_punches.length > 0 ? (
                <div className="overflow-x-auto rounded-md border border-border">
                  <table className="w-full text-sm">
                    <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">Direction</th>
                        <th className="px-3 py-2 text-left font-medium">Requested time</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {request.requested_punches.map((punch) => (
                        <tr key={punch.id}>
                          <td className="px-3 py-2">{punch.direction}</td>
                          <td className="px-3 py-2">{formatDateTime(punch.requested_time)}</td>
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
              <h2 className="mb-4 text-sm font-medium text-foreground">Review</h2>
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field label="Reviewed at" value={formatDateTime(request.reviewed_at)} />
                <Field label="Reviewer comment" value={request.reviewer_comment ?? "—"} />
                <Field label="Rejection reason" value={request.rejection_reason ?? "—"} />
                <Field label="Applied at" value={formatDateTime(request.applied_at)} />
                <Field label="Cancelled at" value={formatDateTime(request.cancelled_at)} />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Timeline</h2>
              <ol className="space-y-3">
                {request.actions.map((entry) => (
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
                      {formatDateTime(entry.created_at)}
                    </span>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        </div>
      ) : null}

      <RegularizationReviewDialog
        open={reviewAction !== null}
        onOpenChange={(open) => !open && setReviewAction(null)}
        request={request}
        action={reviewAction ?? "approve"}
        onDone={(updated) => setRequest(updated)}
      />

      <Dialog open={cancelOpen} onOpenChange={(open) => (!cancelling ? setCancelOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel this request?</DialogTitle>
            <DialogDescription>
              This withdraws the request before it's reviewed. It cannot be undone — you would need
              to submit a new request.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCancelOpen(false)} disabled={cancelling}>
              Keep request
            </Button>
            <Button type="button" variant="destructive" onClick={() => void handleCancel()} disabled={cancelling}>
              {cancelling ? "Cancelling…" : "Cancel request"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
