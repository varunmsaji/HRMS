"use client";

import { CircleCheck } from "lucide-react";
import Link from "next/link";

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { AttentionItem, DayBucket, DayFlag, Severity } from "@/lib/attendance/dashboard";

const SEVERITY_BADGE: Record<Severity, { variant: NonNullable<BadgeProps["variant"]>; label: string }> = {
  critical: { variant: "danger", label: "Critical" },
  high: { variant: "warning", label: "High" },
  medium: { variant: "info", label: "Medium" },
  low: { variant: "outline", label: "Low" },
};

interface NeedsAttentionProps {
  items: AttentionItem[];
  /** Sources that could not be loaded — shown so a missing count is never read as "zero". */
  unavailableSources: string[];
  rangeLabel: string;
  /** Every item here is counted over the whole selected range, not the focus date — the drill
   * must say so (`scope: "range"`) so the page filters the same `rangeRows` population the count
   * came from, not just the focus date (F5-1). */
  onDrill: (target: { bucket?: DayBucket; flag?: DayFlag; scope: "range" }) => void;
}

/** Operational action centre. A row only offers an action that exists: a filter over the loaded
 * days, or a link to the module that owns the workflow (regularizations, overtime, periods). */
export function NeedsAttention({ items, unavailableSources, rangeLabel, onDrill }: NeedsAttentionProps) {
  const { can } = usePermissions();

  function linkLabel(item: AttentionItem): string {
    if (item.key === "pending_regularization") return can("ATTENDANCE.REGULARIZATION_APPROVE") ? "Review" : "View";
    if (item.key === "pending_overtime") return can("ATTENDANCE.OVERTIME_APPROVE") ? "Review" : "View";
    return "Open period";
  }

  return (
    <div className="space-y-3">
      {items.length === 0 ? (
        <div className="flex items-center gap-2 rounded-md bg-success-subtle px-4 py-3 text-sm text-foreground">
          <CircleCheck className="h-4 w-4 text-success" aria-hidden="true" />
          Nothing needs attention for {rangeLabel}.
        </div>
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {items.map((item) => {
            const sev = SEVERITY_BADGE[item.severity];
            return (
              <li key={item.key} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                <Badge variant={sev.variant}>{sev.label}</Badge>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-foreground">
                    {item.label}
                    <span className="ml-2 tabular-nums text-foreground-secondary">
                      {item.count} {item.count === 1 ? item.unit.replace(/s$/, "") : item.unit}
                    </span>
                  </p>
                  <p className="text-xs text-foreground-muted">
                    {item.employees !== null ? `${item.employees} employee${item.employees === 1 ? "" : "s"} affected · ` : ""}
                    {item.hint}
                  </p>
                </div>
                {item.href ? (
                  <Button asChild size="sm" variant="outline">
                    <Link href={item.href}>{linkLabel(item)} →</Link>
                  </Button>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => onDrill({ bucket: item.bucket, flag: item.flag, scope: "range" })}
                    aria-label={`View all: ${item.label}`}
                  >
                    View all →
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {unavailableSources.length > 0 ? (
        <p className="text-xs text-foreground-muted">
          Not included (couldn&apos;t be loaded): {unavailableSources.join(", ")}.
        </p>
      ) : null}
    </div>
  );
}
