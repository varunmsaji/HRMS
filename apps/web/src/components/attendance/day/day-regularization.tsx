"use client";

import Link from "next/link";

import { RegularizationStatusBadge } from "@/components/regularization/regularization-status-badge";
import { Button } from "@/components/ui/button";
import { relativeTime } from "@/lib/dashboard/insights";
import { REGULARIZATION_TYPE_LABELS, type RegularizationRequest } from "@/lib/regularization/types";

interface Props {
  /** Requests for this employee and date; null = still loading or unavailable. */
  requests: RegularizationRequest[] | null;
  /** Whether the viewer can raise a correction for this day. */
  canRequest: boolean;
  /** The day has something a correction could fix. */
  needsCorrection: boolean;
  onRequest: () => void;
}

/** Corrections raised for this day, and a way to raise one. Hidden when the viewer has no way to
 * raise one and none exist; the button is emphasised only when the day looks like it needs fixing. */
export function DayRegularization({ requests, canRequest, needsCorrection, onRequest }: Props) {
  const list = requests ?? [];
  const open = list.some((r) => r.status === "SUBMITTED");
  if (list.length === 0 && !canRequest) return null;
  return (
    <section aria-label="Corrections" className="rounded-2xl border border-border bg-surface p-6 shadow-elevation-1">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-foreground">Corrections</h2>
        {canRequest && !open ? (
          <Button type="button" size="sm" variant={needsCorrection ? "default" : "outline"} onClick={onRequest}>
            Request a correction
          </Button>
        ) : null}
      </div>
      {list.length === 0 ? (
        <p className="text-sm text-foreground-muted">No correction has been requested for this day.</p>
      ) : (
        <ul className="space-y-3">
          {list.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 text-sm">
              <span className="font-medium text-foreground">
                {REGULARIZATION_TYPE_LABELS[r.request_type as keyof typeof REGULARIZATION_TYPE_LABELS] ?? r.request_type}
              </span>
              <RegularizationStatusBadge status={r.status} />
              <span className="text-xs text-foreground-muted">submitted {relativeTime(r.submitted_at)}</span>
              <Link href={`/app/regularizations/${r.id}`} className="ml-auto text-xs font-medium text-primary hover:underline">
                View
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
