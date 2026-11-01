"use client";

import { CheckCircle2, Clock, FileClock } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { useToast } from "@/components/common/toast";
import { Avatar, CARD } from "@/components/dashboard/dashboard-cards";
import { RegularizationReviewDialog } from "@/components/regularization/regularization-review-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useApiResource } from "@/hooks/use-api-resource";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { formatClockTime, formatMinutes } from "@/lib/attendance/format";
import { relativeTime } from "@/lib/dashboard/insights";
import {
  regularizationDecisionPath,
  requestedTime,
  stageLabel,
  type RegularizationDecisionData,
  type RegularizationItem,
  type RegularizationTab,
} from "@/lib/regularization/decision-center";
import {
  REGULARIZATION_TYPE_LABELS,
  type RegularizationRequest,
  type RegularizationType,
} from "@/lib/regularization/types";
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

function Cell({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div>
      <p className="text-2xs uppercase tracking-wider text-foreground-muted">{label}</p>
      <p className={cn("mt-1 text-sm font-semibold tabular-nums text-foreground", tone)}>{value}</p>
    </div>
  );
}

function RequestCard({
  item,
  canReview,
  onReview,
}: {
  item: RegularizationItem;
  canReview: boolean;
  onReview: (id: string, action: "approve" | "reject") => void;
}) {
  const tz = item.timezone ?? "Asia/Kolkata";
  const pending = item.status === "SUBMITTED";
  const reqIn = requestedTime(item.requested_punches, "IN");
  const reqOut = requestedTime(item.requested_punches, "OUT");
  const typeLabel = REGULARIZATION_TYPE_LABELS[item.request_type as RegularizationType] ?? item.request_type;
  return (
    <article className={cn(CARD, "space-y-5 p-6")} aria-label={`${typeLabel} request from ${item.employee_name}`}>
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
            <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-foreground-muted">
              <span>
                Dispute: <CompanyDate value={item.attendance_date} />
              </span>
              {item.shift_name ? <span>Shift: {item.shift_name}</span> : null}
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" aria-hidden="true" /> Submitted {relativeTime(item.submitted_at)}
              </span>
            </p>
          </div>
        </div>
        <Badge variant={pending ? "warning" : item.status === "APPROVED" ? "success" : "secondary"}>
          {pending ? stageLabel(item.approval_stage) : item.status.toLowerCase()}
        </Badge>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-3 rounded-xl bg-muted/50 p-4">
          <p className="text-2xs font-semibold uppercase tracking-wider text-foreground-muted">Recorded by system</p>
          <div className="grid grid-cols-3 gap-3">
            <Cell label="Punch in" value={formatClockTime(item.recorded_first_in, tz)} />
            <Cell
              label="Punch out"
              value={item.recorded_last_out ? formatClockTime(item.recorded_last_out, tz) : "Missing"}
              tone={item.recorded_last_out ? undefined : "text-danger"}
            />
            <Cell label="Worked" value={formatMinutes(item.recorded_worked_minutes)} />
          </div>
          <p className="text-xs text-foreground-muted">
            Status {item.recorded_status ? item.recorded_status.replaceAll("_", " ").toLowerCase() : "not recorded"}
            {item.recorded_late_minutes ? ` · ${item.recorded_late_minutes}m late` : ""}
          </p>
        </div>

        <div className="space-y-3 rounded-xl border border-primary-border bg-primary-subtle/40 p-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-2xs font-semibold uppercase tracking-wider text-primary">Requested correction</p>
            <span className="text-xs font-medium text-primary">{typeLabel}</span>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <Cell label="Punch in" value={reqIn ? formatClockTime(reqIn, tz) : "No change"} />
            <Cell label="Punch out" value={reqOut ? formatClockTime(reqOut, tz) : "No change"} />
            <Cell label="Projected" value={item.requested_span_minutes ? formatMinutes(item.requested_span_minutes) : "—"} />
          </div>
          <p className="text-xs text-foreground-muted">
            Projected is the span between the first in and last out; the engine recalculates the final hours on approval.
          </p>
        </div>
      </div>

      {item.reason ? (
        <p className="rounded-xl bg-muted/50 p-3 text-sm text-foreground-secondary">
          <span className="mr-1 text-2xs font-semibold uppercase tracking-wider text-foreground-muted">
            Employee reason
          </span>
          “{item.reason}”
        </p>
      ) : null}

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <Link href={`/app/regularizations/${item.id}`} className="text-sm font-medium text-primary hover:underline">
          View full audit trail
        </Link>
        {pending && canReview ? (
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" onClick={() => onReview(item.id, "reject")}>
              Decline
            </Button>
            <Button type="button" onClick={() => onReview(item.id, "approve")}>
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              Approve regularization
            </Button>
          </div>
        ) : null}
      </footer>
    </article>
  );
}

const TABS: { key: RegularizationTab; label: string }[] = [
  { key: "pending", label: "Pending review" },
  { key: "approved", label: "Approved history" },
  { key: "declined", label: "Declined" },
];

/** The approver's regularization decision center. Deciding reuses the existing review dialog and routes. */
export function RegularizationDecisionCenter() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [tab, setTab] = useState<RegularizationTab>("pending");
  const { data, loading, error, retry } = useApiResource<RegularizationDecisionData>(regularizationDecisionPath(tab));
  const [reviewing, setReviewing] = useState<{ request: RegularizationRequest; action: "approve" | "reject" } | null>(
    null,
  );

  async function openReview(id: string, action: "approve" | "reject") {
    try {
      const request = await apiClient.get<RegularizationRequest>(`/regularizations/${id}`);
      setReviewing({ request, action });
    } catch (err) {
      toast({ title: "Could not open request", description: describeApiError(err), variant: "danger" });
    }
  }

  const s = data?.summary;
  return (
    <div className="space-y-5">
      <section aria-label="Regularization overview" className="grid grid-cols-1 gap-5 sm:grid-cols-3">
        <Stat
          label="Pending decisions"
          value={s ? s.pending_count : "—"}
          tag={s && s.pending_count > 0 ? <Badge variant="warning">Action required</Badge> : null}
          note={s?.oldest_pending_at ? `Oldest submitted ${relativeTime(s.oldest_pending_at)}` : s ? "Nothing waiting" : undefined}
        />
        <Stat
          label="Regularization rate (last 30 days)"
          value={s?.window_rate_pct != null ? `${s.window_rate_pct}%` : "—"}
          note={s ? `${s.window_regularized_days} of ${s.window_expected_days} working days regularized` : undefined}
        />
        <Stat
          label="Approved / declined"
          value={data ? `${data.counts.approved} / ${data.counts.declined}` : "—"}
          note="All time, within your access"
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
          message={error.status === 403 ? "You do not have permission to review regularizations." : error.message}
          onRetry={retry}
        />
      ) : loading && !data ? (
        <p className="py-10 text-center text-sm text-foreground-muted">Loading…</p>
      ) : data && data.items.length === 0 ? (
        <EmptyState icon={FileClock} title="No requests here." description="Nothing to show for this tab." />
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
              Showing {data.items.length} of {data.counts[tab]}. Use “Team requests” to filter further.
            </p>
          ) : null}
        </div>
      )}

      <RegularizationReviewDialog
        open={reviewing !== null}
        onOpenChange={(open) => !open && setReviewing(null)}
        request={reviewing?.request ?? null}
        action={reviewing?.action ?? "approve"}
        onDone={() => {
          setReviewing(null);
          retry();
        }}
      />
    </div>
  );
}
