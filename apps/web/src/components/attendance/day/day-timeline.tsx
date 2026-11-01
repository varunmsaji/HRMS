"use client";

import { AlertTriangle, Coffee, LogIn, LogOut, type LucideIcon } from "lucide-react";

import { formatClockTime } from "@/lib/attendance/format";
import type { TimelineItem } from "@/lib/attendance/day-detail";
import { cn } from "@/lib/utils";

const ICONS: Record<TimelineItem["kind"], { icon: LucideIcon; tone: string }> = {
  IN: { icon: LogIn, tone: "bg-success-subtle text-success" },
  OUT: { icon: LogOut, tone: "bg-info-subtle text-info" },
  BREAK_START: { icon: Coffee, tone: "bg-warning-subtle text-warning" },
  BREAK_END: { icon: Coffee, tone: "bg-warning-subtle text-warning" },
  MISSING_OUT: { icon: AlertTriangle, tone: "bg-danger-subtle text-danger" },
};

/** Punches and break events in order, with where each came from. `items` null = still loading. */
export function DayTimeline({ items, timezone }: { items: TimelineItem[] | null; timezone: string }) {
  return (
    <section aria-label="Punch timeline" className="rounded-2xl border border-border bg-surface p-6 shadow-elevation-1">
      <h2 className="mb-4 text-base font-semibold text-foreground">Punch timeline</h2>
      {items === null ? (
        <p className="text-sm text-foreground-muted">Loading punches…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-foreground-muted">No punches or breaks recorded for this day.</p>
      ) : (
        <ol className="space-y-4">
          {items.map((item) => {
            const { icon: Icon, tone } = ICONS[item.kind];
            return (
              <li key={item.key} className="flex items-start gap-3">
                <span className={cn("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full", tone)}>
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className={cn("text-sm font-medium", item.kind === "MISSING_OUT" ? "text-danger" : "text-foreground")}>
                    {item.label}
                  </p>
                  {item.source ? <p className="text-xs text-foreground-muted">{item.source}</p> : null}
                </div>
                <span className="shrink-0 text-sm tabular-nums text-foreground-secondary">
                  {item.time ? formatClockTime(item.time, timezone) : "—"}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
