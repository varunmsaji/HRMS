"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { LeaveApplicationReviewDialog } from "@/components/leave-application/leave-application-review-dialog";
import { LeaveApplicationStatusBadge } from "@/components/leave-application/leave-application-status-badge";
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
import type { LeaveApplication } from "@/lib/leave-application/types";

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
};

/** `GET /v1/leave-applications/{id}` detail (LEAVE_DECISION_LOG.md LD-02/LD-05/LD-12/LD-13).
 * Shows the original application, its per-day breakdown (including any sandwich-rule-generated
 * days), and the append-only action timeline. */
export default function LeaveApplicationDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { toast } = useToast();
  const { user } = useAuth();
  const { can } = usePermissions();

  const [application, setApplication] = useState<LeaveApplication | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [reviewAction, setReviewAction] = useState<"approve" | "reject" | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<LeaveApplication>(`/leave-applications/${params.id}`);
      setApplication(data);
    } catch (err) {
      setApplication(null);
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
    if (!application) return;
    setCancelling(true);
    try {
      const updated = await apiClient.post<LeaveApplication>(
        `/leave-applications/${application.id}/cancel`,
        {},
        { ifMatch: String(application.version) },
      );
      setApplication(updated);
      setCancelOpen(false);
      toast({
        title:
          updated.status === "CANCELLED" && application.status === "APPROVED"
            ? "Application cancelled — balance and attendance reversed"
            : "Application cancelled",
        variant: "success",
      });
    } catch (err) {
      toast({ title: "Could not cancel", description: describeApiError(err), variant: "danger" });
    } finally {
      setCancelling(false);
    }
  }

  const canApprove = can("LEAVE.APPLICATION_APPROVE");
  const isPending = application?.status === "SUBMITTED" && application.approval_stage !== null;
  const isOwnApplication = Boolean(
    user?.employee_id && application?.employee_id === user.employee_id,
  );
  const canReview = canApprove && isPending && !isOwnApplication;
  // LD-13: cancel is available while SUBMITTED or already APPROVED, always submitter-only.
  const canCancel =
    (application?.status === "SUBMITTED" || application?.status === "APPROVED") &&
    application?.submitted_by_user_id === user?.id;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Leave application"
        description={
          application
            ? application.start_date === application.end_date
              ? application.start_date
              : `${application.start_date} – ${application.end_date}`
            : undefined
        }
        actions={
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" onClick={() => router.push("/app/leave-applications")}>
              Back to leave applications
            </Button>
            {canCancel ? (
              <Button type="button" variant="outline" onClick={() => setCancelOpen(true)}>
                Cancel application
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

      {loading ? <LoadingState label="Loading leave application…" fullPage /> : null}
      {error && !loading ? (
        <ErrorState
          message={
            error.status === 404
              ? "This application was not found, or you don't have access to it."
              : error.message
          }
          onRetry={() => void load()}
        />
      ) : null}

      {!loading && !error && application ? (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <LeaveApplicationStatusBadge status={application.status} />
            {application.approval_stage ? (
              <Badge variant="outline">Pending {application.approval_stage.toLowerCase()} review</Badge>
            ) : null}
          </div>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Application</h2>
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field label="Total days" value={application.total_days} />
                <Field label="Reason" value={application.reason ?? "—"} />
                <Field label="Attachment reference" value={application.attachment_reference ?? "—"} />
                <Field label="Approval chain" value={application.approval_chain} />
                <Field label="Approval stage" value={application.approval_stage ?? "—"} />
                <Field label="Submitted at" value={formatDateTime(application.submitted_at)} />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Day breakdown</h2>
              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full text-sm">
                  <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Date</th>
                      <th className="px-3 py-2 text-right font-medium">Fraction</th>
                      <th className="px-3 py-2 text-left font-medium">Half</th>
                      <th className="px-3 py-2 text-left font-medium">Sandwich rule</th>
                      <th className="px-3 py-2 text-left font-medium">Attendance projection</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {application.days.map((day) => (
                      <tr key={day.id}>
                        <td className="px-3 py-2">{day.calendar_date}</td>
                        <td className="px-3 py-2 text-right">{day.fraction}</td>
                        <td className="px-3 py-2">{day.half ?? "—"}</td>
                        <td className="px-3 py-2">{day.is_sandwich_generated ? "Yes" : "—"}</td>
                        <td className="px-3 py-2">
                          {day.leave_day_projection_id ? (
                            <a
                              href={`/app/attendance?projection=${day.leave_day_projection_id}`}
                              className="text-primary hover:underline"
                            >
                              Synced
                            </a>
                          ) : (
                            "Not synced"
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Review</h2>
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Field label="Reviewed at" value={formatDateTime(application.reviewed_at)} />
                <Field label="Reviewer comment" value={application.reviewer_comment ?? "—"} />
                <Field label="Rejection reason" value={application.rejection_reason ?? "—"} />
                <Field label="Cancelled at" value={formatDateTime(application.cancelled_at)} />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">Timeline</h2>
              <ol className="space-y-3">
                {application.actions.map((entry) => (
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

      <LeaveApplicationReviewDialog
        open={reviewAction !== null}
        onOpenChange={(open) => !open && setReviewAction(null)}
        application={application}
        action={reviewAction ?? "approve"}
        onDone={(updated) => setApplication(updated)}
      />

      <Dialog open={cancelOpen} onOpenChange={(open) => (!cancelling ? setCancelOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel this application?</DialogTitle>
            <DialogDescription>
              {application?.status === "APPROVED"
                ? "This reverses the balance debit and cancels every synced attendance projection for this application. It cannot be undone."
                : "This withdraws the application before it's reviewed. It cannot be undone."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCancelOpen(false)} disabled={cancelling}>
              Keep application
            </Button>
            <Button type="button" variant="destructive" onClick={() => void handleCancel()} disabled={cancelling}>
              {cancelling ? "Cancelling…" : "Cancel application"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
