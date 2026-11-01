"use client";

import { AlertTriangle, CalendarOff, CheckCircle2, Clock } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { useToast } from "@/components/common/toast";
import { Avatar, CARD } from "@/components/dashboard/dashboard-cards";
import { LeaveApplicationReviewDialog } from "@/components/leave-application/leave-application-review-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useApiResource } from "@/hooks/use-api-resource";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { relativeTime } from "@/lib/dashboard/insights";
import {
  clashSummary,
  days,
  decisionCenterPath,
  type DecisionCenterData,
  type DecisionItem,
  type DecisionTab,
} from "@/lib/leave-application/decision-center";
import type { LeaveApplication } from "@/lib/leave-application/types";
import { cn } from "@/lib/utils";

function Stat({ label, value, note, tag }: { label: string; value: ReactNode; note?: ReactNode; tag?: ReactNode }) {
  return (
    <div className={CARD}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-foreground-secondary">{label}</p>
        {tag}
      </div>
      <p className="mt-2 text-3xl font-bold tabular-nums tracking-tight text-foreground">{value}</p>
      {note ? <p className="mt-3 border-t border-border pt-3 text-xs text-foreground-muted">{note}</p> : null}
    </div>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-foreground-secondary">{label}</span>
      <span className={cn("font-medium tabular-nums text-foreground", tone)}>{value}</span>
    </div>
  );
}

function RequestCard({
  item,
  canReview,
  onReview,
}: {
  item: DecisionItem;
  canReview: boolean;
  onReview: (id: string, action: "approve" | "reject") => void;
}) {
  const pending = item.status === "SUBMITTED";
  const clash = clashSummary(item);
  const lop = Number(item.lop_days);
  const paid = Number(item.total_days) - lop;
  return (
    <article className={cn(CARD, "space-y-5 p-6")} aria-label={`${item.leave_type} request from ${item.employee_name}`}>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <Avatar name={item.employee_name} />
          <div className="min-w-0">
            <p className="font-semibold text-foreground">
              {item.employee_name} <span className="font-normal text-foreground-muted">({item.employee_code})</span>
            </p>
            <p className="text-xs text-foreground-secondary">
              {[item.designation, item.department].filter(Boolean).join(" • ") || "—"}
            </p>
            <p className="mt-0.5 flex items-center gap-1 text-xs text-foreground-muted">
              <Clock className="h-3 w-3" aria-hidden="true" /> Submitted {relativeTime(item.submitted_at)}
            </p>
          </div>
        </div>
        <Badge variant={pending ? "warning" : item.status === "APPROVED" ? "success" : "secondary"}>
          {pending ? "Pending approval" : item.status.toLowerCase()}
        </Badge>
      </header>

      <div className={cn("grid gap-4", pending ? "md:grid-cols-2" : "")}>
        <div className="space-y-3 rounded-xl bg-muted/50 p-4">
          <p className="text-2xs font-semibold uppercase tracking-wider text-foreground-muted">Leave particulars</p>
          <p className="flex flex-wrap items-center gap-2 text-sm">
            <Badge variant="secondary">{item.leave_type}</Badge>
            <span className="font-medium text-foreground">
              {days(item.total_days)} {Number(item.total_days) === 1 ? "day" : "days"}
            </span>
          </p>
          <p className="text-sm text-foreground-secondary">
            <CompanyDate value={item.start_date} />
            {item.end_date !== item.start_date ? (
              <>
                {" – "}
                <CompanyDate value={item.end_date} />
              </>
            ) : null}
          </p>
          {item.reason ? (
            <p className="rounded-lg border border-border bg-surface p-3 text-sm text-foreground-secondary">
              Reason: “{item.reason}”
            </p>
          ) : null}
        </div>

        {pending && item.current_balance !== null ? (
          <div className="space-y-2 rounded-xl bg-muted/50 p-4">
            <p className="text-2xs font-semibold uppercase tracking-wider text-foreground-muted">
              Balance deduction
            </p>
            <Row label="Current balance" value={`${days(item.current_balance)} days`} />
            <Row label="Requested deduction" value={`−${days(paid)} days`} tone="text-danger" />
            <div className="border-t border-border pt-2">
              <Row
                label="Post-approval balance"
                value={`${days(item.post_approval_balance)} days`}
                tone={Number(item.post_approval_balance) < 0 ? "text-danger" : "text-success"}
              />
            </div>
            {lop > 0 ? (
              <p className="flex items-center gap-2 rounded-lg bg-warning-subtle p-2.5 text-xs text-warning">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                {days(lop)} {lop === 1 ? "day" : "days"} will be treated as loss of pay.
              </p>
            ) : (
              <p className="flex items-center gap-2 text-xs text-success">
                <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                Covered by the available balance.
              </p>
            )}
          </div>
        ) : null}
      </div>

      {pending ? (
        <p
          className={cn(
            "flex items-center gap-2 rounded-xl p-3 text-sm",
            clash.clash ? "bg-warning-subtle text-warning" : "bg-success-subtle text-success",
          )}
        >
          {clash.clash ? (
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
          ) : (
            <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
          )}
          {clash.text}
        </p>
      ) : null}

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <Link href={`/app/leave-applications/${item.id}`} className="text-sm font-medium text-primary hover:underline">
          View details
        </Link>
        {pending && canReview ? (
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" onClick={() => onReview(item.id, "reject")}>
              Decline
            </Button>
            <Button type="button" onClick={() => onReview(item.id, "approve")}>
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              Approve leave
            </Button>
          </div>
        ) : null}
      </footer>
    </article>
  );
}

const TABS: { key: DecisionTab; label: string }[] = [
  { key: "pending", label: "Pending approvals" },
  { key: "approved", label: "Approved leaves" },
  { key: "declined", label: "Declined & cancelled" },
];

/** The approver's decision center. Approve/decline reuse the existing review dialog and routes. */
export function LeaveDecisionCenter() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [tab, setTab] = useState<DecisionTab>("pending");
  const { data, loading, error, retry } = useApiResource<DecisionCenterData>(decisionCenterPath(tab));
  const [reviewing, setReviewing] = useState<{ application: LeaveApplication; action: "approve" | "reject" } | null>(null);

  async function openReview(id: string, action: "approve" | "reject") {
    try {
      const application = await apiClient.get<LeaveApplication>(`/leave-applications/${id}`);
      setReviewing({ application, action });
    } catch (err) {
      toast({ title: "Could not open request", description: describeApiError(err), variant: "danger" });
    }
  }

  const s = data?.summary;
  const oldest = s?.oldest_pending_at ? relativeTime(s.oldest_pending_at) : null;
  const byType = s?.on_leave_today_by_type.map(([name, n]) => `${n} ${name.replace(/ Leave$/, "")}`).join(", ");

  return (
    <div className="space-y-5">
      <section aria-label="Leave overview" className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Pending requests"
          value={s ? s.pending_count : "—"}
          tag={s && s.pending_count > 0 ? <Badge variant="warning">Action required</Badge> : null}
          note={oldest ? `Oldest submitted ${oldest}` : s ? "Nothing waiting" : undefined}
        />
        <Stat
          label="On leave today"
          value={s ? s.on_leave_today : "—"}
          note={s ? (byType || "Everyone is in") + ` · ${s.active_staff} active staff` : undefined}
        />
        <Stat
          label="Approved starts, next 7 days"
          value={s ? s.upcoming_starts_7d : "—"}
          note={
            s?.peak_day ? (
              <>
                Peak absence: <CompanyDate value={s.peak_day} /> ({s.peak_day_away} away)
              </>
            ) : s ? (
              "No approved leave in the next 7 days"
            ) : undefined
          }
        />
        <Stat
          label="Staff available today"
          value={s?.available_pct != null ? `${Math.round(s.available_pct)}%` : "—"}
          note={s ? `${s.on_leave_today} of ${s.active_staff} on leave` : undefined}
        />
      </section>

      <div role="tablist" aria-label="Request status" className="flex flex-wrap gap-1 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            type="button"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              "-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors",
              tab === t.key
                ? "border-primary text-primary"
                : "border-transparent text-foreground-secondary hover:text-foreground",
            )}
          >
            {t.label}
            {data ? (
              <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-2xs tabular-nums">{data.counts[t.key]}</span>
            ) : null}
          </button>
        ))}
      </div>

      {error ? (
        <ErrorState
          message={error.status === 403 ? "You do not have permission to review leave requests." : error.message}
          onRetry={retry}
        />
      ) : loading && !data ? (
        <p className="py-10 text-center text-sm text-foreground-muted">Loading…</p>
      ) : data && data.items.length === 0 ? (
        <EmptyState icon={CalendarOff} title="No requests here." description="Nothing to show for this tab." />
      ) : (
        <div className="space-y-5">
          {data?.items.map((item) => (
            <RequestCard
              key={item.id}
              item={item}
              canReview={item.employee_id !== user?.employee_id}
              onReview={openReview}
            />
          ))}
          {data && data.counts[tab] > data.items.length ? (
            <p className="text-center text-xs text-foreground-muted">
              Showing {data.items.length} of {data.counts[tab]}. Use “Team applications” to filter further.
            </p>
          ) : null}
        </div>
      )}

      <LeaveApplicationReviewDialog
        open={reviewing !== null}
        onOpenChange={(open) => !open && setReviewing(null)}
        application={reviewing?.application ?? null}
        action={reviewing?.action ?? "approve"}
        onDone={() => {
          setReviewing(null);
          retry();
        }}
      />
    </div>
  );
}
