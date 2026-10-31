"use client";

import { CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import { SectionCard } from "@/components/attendance/dashboard/section-card";
import {
  PENDING_PREVIEW_SIZE,
  usePendingApprovals,
  type PendingCategory,
} from "@/components/dashboard/use-pending-approvals";
import { LeaveApplicationReviewDialog } from "@/components/leave-application/leave-application-review-dialog";
import { OvertimeReviewDialog } from "@/components/overtime/overtime-review-dialog";
import { RegularizationReviewDialog } from "@/components/regularization/regularization-review-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useApiResource } from "@/hooks/use-api-resource";
import { usePermissions } from "@/lib/auth/use-permissions";
import { useAuth } from "@/lib/auth/auth-context";
import { formatMinutes } from "@/lib/attendance/format";
import {
  formatCompanyDate,
  formatCompanyDateInZone,
} from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import { ONBOARDING_STATUS_LABELS } from "@/lib/dashboard/overview";
import { useEmployeeNames } from "@/lib/employee/use-employee-names";
import type { LeaveApplication } from "@/lib/leave-application/types";
import type { LeaveType } from "@/lib/leave-type/types";
import type { OnboardingCase } from "@/lib/onboarding/types";
import type { OvertimeRecord } from "@/lib/overtime/types";
import {
  REGULARIZATION_TYPE_LABELS,
  type RegularizationRequest,
} from "@/lib/regularization/types";

type Review =
  | { kind: "leave"; item: LeaveApplication; action: "approve" | "reject" }
  | {
      kind: "regularization";
      item: RegularizationRequest;
      action: "approve" | "reject";
    }
  | { kind: "overtime"; item: OvertimeRecord; action: "approve" | "reject" };

function Stage({ stage }: { stage: string | null }) {
  return stage ? <Badge variant="secondary">{stage} stage</Badge> : null;
}

/** How many of the newest pending requests the collapsed card lists. */
const LATEST_COUNT = 5;

interface RowProps {
  name: string;
  detail: ReactNode;
  submitted: string;
  badge?: ReactNode;
  actions: ReactNode;
  /** Category label, shown in the combined "latest" list where rows of all queues mix. */
  kind?: string;
}

function Row({ name, detail, submitted, badge, actions, kind }: RowProps) {
  return (
    <li className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="flex items-center gap-2 text-sm font-medium text-foreground">
          <span className="truncate">{name}</span>
          {kind ? <Badge variant="outline">{kind}</Badge> : null}
        </p>
        <p className="text-xs text-foreground-secondary">{detail}</p>
        <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-foreground-muted">
          <span>Submitted {submitted}</span>
          {badge}
        </p>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>
    </li>
  );
}

function Group<T>({
  title,
  href,
  category,
  children,
}: {
  title: string;
  href: string;
  category: PendingCategory<T>;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="min-w-0">
      <div className="flex items-center justify-between gap-2 border-b border-border pb-2">
        <h3 className="text-sm font-semibold text-foreground">
          {title}{" "}
          <span className="ml-1 tabular-nums text-foreground-secondary">
            ({category.total})
          </span>
        </h3>
        <Link
          href={href}
          className="text-xs font-medium text-primary hover:underline"
        >
          {category.total > PENDING_PREVIEW_SIZE
            ? `View all ${category.total}`
            : "Open"}
        </Link>
      </div>
      {category.error ? (
        <p className="py-3 text-xs text-danger">
          {category.error.status === 403
            ? "You do not have access to this queue."
            : "Couldn't load this queue."}
        </p>
      ) : category.items.length === 0 ? (
        <p className="py-3 text-xs text-foreground-muted">Nothing pending.</p>
      ) : (
        <ul className="divide-y divide-border">{children}</ul>
      )}
    </section>
  );
}

export function PendingApprovals() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const datePattern = useCompanyDatePattern();
  const tz = user?.company_timezone ?? "Asia/Kolkata";

  const canLeave = can("LEAVE.APPLICATION_APPROVE");
  const canReg = can("ATTENDANCE.REGULARIZATION_APPROVE");
  const canOt = can("ATTENDANCE.OVERTIME_APPROVE");
  const canOnboarding = can("ONBOARDING.REVIEW") && can("ONBOARDING.VIEW");

  const { data, loading, refresh } = usePendingApprovals({
    leave: canLeave,
    regularization: canReg,
    overtime: canOt,
    onboarding: canOnboarding,
  });
  const leaveTypes = useApiResource<LeaveType[]>("/leave-types");
  const [review, setReview] = useState<Review | null>(null);
  const [expanded, setExpanded] = useState(false);

  const employeeIds = useMemo(
    () => [
      ...(data?.leave?.items ?? []).map((i) => i.employee_id),
      ...(data?.regularization?.items ?? []).map((i) => i.employee_id),
      ...(data?.overtime?.items ?? []).map((i) => i.employee_id),
    ],
    [data],
  );
  const employeeName = useEmployeeNames(employeeIds);
  const leaveTypeName = (id: string) =>
    leaveTypes.data?.find((t) => t.id === id)?.name ?? "Leave";
  const day = (iso: string) => formatCompanyDate(iso, datePattern);
  const when = (iso: string) => formatCompanyDateInZone(iso, tz, datePattern);

  const total =
    (data?.leave?.total ?? 0) +
    (data?.regularization?.total ?? 0) +
    (data?.overtime?.total ?? 0) +
    (data?.onboardingHr?.total ?? 0) +
    (data?.onboardingCandidate?.total ?? 0);
  const visible = canLeave || canReg || canOt || canOnboarding;
  const queueFailed = !!data && Object.values(data).some((c) => c?.error);

  const summary = [
    {
      label: "Leave requests",
      n: data?.leave?.total,
      href: "/app/leave-applications?status=SUBMITTED",
      on: canLeave,
    },
    {
      label: "Attendance regularization",
      n: data?.regularization?.total,
      href: "/app/regularizations?status=SUBMITTED",
      on: canReg,
    },
    {
      label: "Overtime",
      n: data?.overtime?.total,
      href: "/app/overtime?status=PENDING",
      on: canOt,
    },
    {
      label: "Onboarding — HR review",
      n: data?.onboardingHr?.total,
      href: "/app/onboarding?status=SUBMITTED",
      on: canOnboarding,
    },
    {
      label: "Onboarding — awaiting candidate",
      n: data?.onboardingCandidate?.total,
      href: "/app/onboarding?status=INVITED",
      on: canOnboarding,
    },
  ].filter((s) => s.on);

  function reviewButtons(r: Review) {
    return (
      <>
        <Button
          size="sm"
          onClick={() => setReview({ ...r, action: "approve" })}
        >
          Approve
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setReview({ ...r, action: "reject" })}
        >
          Reject
        </Button>
      </>
    );
  }

  function done() {
    setReview(null);
    void refresh();
  }

  function leaveRow(a: LeaveApplication, kind?: string) {
    return (
      <Row
        key={`leave-${a.id}`}
        kind={kind}
        name={employeeName(a.employee_id)}
        detail={`${leaveTypeName(a.leave_type_id)} · ${day(a.start_date)}${a.end_date !== a.start_date ? ` – ${day(a.end_date)}` : ""} · ${Number(a.total_days)} day${Number(a.total_days) === 1 ? "" : "s"}`}
        submitted={when(a.submitted_at)}
        badge={<Stage stage={a.approval_stage} />}
        actions={reviewButtons({ kind: "leave", item: a, action: "approve" })}
      />
    );
  }

  function regularizationRow(r: RegularizationRequest, kind?: string) {
    return (
      <Row
        key={`reg-${r.id}`}
        kind={kind}
        name={employeeName(r.employee_id)}
        detail={`${REGULARIZATION_TYPE_LABELS[r.request_type] ?? r.request_type} · ${day(r.attendance_date)}${r.reason ? ` · ${r.reason}` : ""}`}
        submitted={when(r.submitted_at)}
        badge={<Stage stage={r.approval_stage} />}
        actions={reviewButtons({
          kind: "regularization",
          item: r,
          action: "approve",
        })}
      />
    );
  }

  function overtimeRow(o: OvertimeRecord, kind?: string) {
    return (
      <Row
        key={`ot-${o.id}`}
        kind={kind}
        name={employeeName(o.employee_id)}
        detail={`${day(o.attendance_date)} · ${formatMinutes(o.minutes_detected)} detected`}
        submitted={when(o.created_at)}
        badge={<Stage stage={o.approval_stage} />}
        actions={reviewButtons({
          kind: "overtime",
          item: o,
          action: "approve",
        })}
      />
    );
  }

  // Newest requests across the approval queues. Onboarding awaiting the candidate is not an
  // approval, so it only appears in the expanded view.
  const latest = [
    ...(data?.leave?.items ?? []).map((a) => ({
      at: a.submitted_at,
      node: leaveRow(a, "Leave"),
    })),
    ...(data?.regularization?.items ?? []).map((r) => ({
      at: r.submitted_at,
      node: regularizationRow(r, "Regularization"),
    })),
    ...(data?.overtime?.items ?? []).map((o) => ({
      at: o.created_at,
      node: overtimeRow(o, "Overtime"),
    })),
    ...(data?.onboardingHr?.items ?? []).map((c) => ({
      at: c.created_at,
      node: (
        <OnboardingRow
          key={`onb-${c.id}`}
          item={c}
          when={when}
          kind="Onboarding"
        />
      ),
    })),
  ]
    .sort((a, b) => b.at.localeCompare(a.at))
    .slice(0, LATEST_COUNT);

  return (
    <SectionCard
      id="pending-approvals"
      title="Pending Requests & Approvals"
      description="Always current — not affected by the attendance date above."
      status={loading && !data ? "loading" : "ready"}
      unavailable={!visible ? "You have no approval queues to review." : null}
    >
      {data && total === 0 && !queueFailed ? (
        <div className="flex items-center justify-center gap-2 rounded-md border border-dashed border-border px-4 py-8 text-sm text-foreground-secondary">
          <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
          No pending requests. You&apos;re all caught up.
        </div>
      ) : null}

      {data && visible && (total > 0 || queueFailed) ? (
        <>
          <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            {summary.map((s) => (
              <li key={s.label} className="min-w-0">
                <Link
                  href={s.href}
                  aria-label={`${s.label}: ${s.n ?? 0} pending`}
                  className="block h-full rounded-lg border border-border bg-surface p-3 hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="block text-2xl font-semibold tabular-nums text-foreground">
                    {s.n ?? 0}
                  </span>
                  <span className="mt-0.5 block text-xs text-foreground-secondary">
                    {s.label}
                  </span>
                </Link>
              </li>
            ))}
          </ul>

          {!expanded && latest.length > 0 ? (
            <section aria-label="Latest pending requests">
              <h3 className="border-b border-border pb-2 text-sm font-semibold text-foreground">
                Latest requests
              </h3>
              <ul className="divide-y divide-border">
                {latest.map((l) => l.node)}
              </ul>
            </section>
          ) : null}

          <div className="flex justify-center">
            <Button
              variant="outline"
              size="sm"
              aria-expanded={expanded}
              onClick={() => setExpanded((e) => !e)}
            >
              {expanded
                ? "Show latest only"
                : `View all pending requests (${total})`}
            </Button>
          </div>

          {expanded ? (
            <div className="grid min-w-0 gap-6 lg:grid-cols-2 [&>*]:min-w-0">
              {data.leave ? (
                <Group
                  title="Leave requests"
                  href="/app/leave-applications?status=SUBMITTED"
                  category={data.leave}
                >
                  {data.leave.items.map((a) => leaveRow(a))}
                </Group>
              ) : null}
              {data.regularization ? (
                <Group
                  title="Attendance regularization"
                  href="/app/regularizations?status=SUBMITTED"
                  category={data.regularization}
                >
                  {data.regularization.items.map((r) => regularizationRow(r))}
                </Group>
              ) : null}
              {data.overtime ? (
                <Group
                  title="Overtime"
                  href="/app/overtime?status=PENDING"
                  category={data.overtime}
                >
                  {data.overtime.items.map((o) => overtimeRow(o))}
                </Group>
              ) : null}
              {data.onboardingHr ? (
                <Group
                  title="Onboarding — HR review"
                  href="/app/onboarding?status=SUBMITTED"
                  category={data.onboardingHr}
                >
                  {data.onboardingHr.items.map((c) => (
                    <OnboardingRow key={c.id} item={c} when={when} />
                  ))}
                </Group>
              ) : null}
              {data.onboardingCandidate ? (
                <Group
                  title="Onboarding — awaiting candidate"
                  href="/app/onboarding?status=INVITED"
                  category={data.onboardingCandidate}
                >
                  {data.onboardingCandidate.items.map((c) => (
                    <OnboardingRow key={c.id} item={c} when={when} />
                  ))}
                </Group>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}

      {review?.kind === "leave" ? (
        <LeaveApplicationReviewDialog
          open
          onOpenChange={(o) => !o && setReview(null)}
          application={review.item}
          action={review.action}
          onDone={done}
        />
      ) : null}
      {review?.kind === "regularization" ? (
        <RegularizationReviewDialog
          open
          onOpenChange={(o) => !o && setReview(null)}
          request={review.item}
          action={review.action}
          onDone={done}
        />
      ) : null}
      {review?.kind === "overtime" ? (
        <OvertimeReviewDialog
          open
          onOpenChange={(o) => !o && setReview(null)}
          record={review.item}
          action={review.action}
          onDone={done}
        />
      ) : null}
    </SectionCard>
  );
}

function OnboardingRow({
  item,
  when,
  kind,
}: {
  item: OnboardingCase;
  when: (iso: string) => string;
  kind?: string;
}) {
  const name = [item.candidate_first_name, item.candidate_last_name]
    .filter(Boolean)
    .join(" ");
  return (
    <Row
      kind={kind}
      name={name}
      detail={ONBOARDING_STATUS_LABELS[item.status] ?? item.status}
      submitted={when(item.created_at)}
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={`/app/onboarding/${item.id}`}>View</Link>
        </Button>
      }
    />
  );
}
