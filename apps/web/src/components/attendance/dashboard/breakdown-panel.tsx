"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { formatPct } from "@/lib/attendance/dashboard";
import type { BreakdownKey, GroupStat } from "@/lib/attendance/insights";
import { cn } from "@/lib/utils";

const LABELS: Record<BreakdownKey, { one: string; many: string }> = {
  department: { one: "department", many: "departments" },
  branch: { one: "branch", many: "branches" },
};
const SHOWN = 8;

interface BreakdownPanelProps {
  byDepartment: GroupStat[];
  byBranch: GroupStat[];
  /** The department / branch filter currently applied, if any. */
  active: { department: string; branch: string };
  /** Clicking a row narrows the whole dashboard to that department / branch (clicking it again clears it). */
  onSelect: (key: BreakdownKey, name: string) => void;
  focusLabel: string;
  /** Set when the figures cover only some employees (the directory has a request ceiling). */
  partialNote?: string | null;
}

function Row({ stat, selected, onClick, label }: { stat: GroupStat; selected: boolean; onClick: () => void; label: string }) {
  const rate = stat.rate;
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        aria-pressed={selected}
        aria-label={`${stat.name}: ${rate === null ? "nobody expected" : formatPct(rate)} present, ${stat.absent} absent, ${stat.late} late. ${selected ? "Clear" : "Show only this"} ${label}.`}
        className={cn(
          "group grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1.5 rounded-lg border px-3 py-2.5 text-left transition-[transform,colors] duration-motion-fast hover:border-border-strong hover:bg-surface-secondary/60 active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transform-none",
          selected ? "border-primary bg-primary-subtle/30 ring-1 ring-primary" : "border-border",
        )}
      >
        <span className="min-w-0 truncate text-sm font-medium text-foreground">{stat.name}</span>
        <span className="flex items-center gap-1.5 text-xs tabular-nums text-foreground-secondary">
          {stat.absent > 0 ? <span className="rounded-full bg-danger-subtle px-1.5 py-0.5 font-medium text-danger">{stat.absent} absent</span> : null}
          {stat.late > 0 ? <span className="rounded-full bg-warning-subtle px-1.5 py-0.5 font-medium text-warning">{stat.late} late</span> : null}
          <span className="w-28 text-right text-foreground-muted">
            {rate === null ? "Nobody expected" : `${stat.present} of ${stat.expected} · ${formatPct(rate)}`}
          </span>
        </span>
        <span className="col-span-2 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <span
            className="block h-full origin-left animate-grow-x rounded-full bg-primary"
            style={{ width: `${rate ?? 0}%` }}
          />
        </span>
      </button>
    </li>
  );
}

/** Attendance for each department or branch on the focus day, lowest first, so the places that need
 * a look are at the top. A row is also a filter: clicking it narrows the whole dashboard. */
export function BreakdownPanel({ byDepartment, byBranch, active, onSelect, focusLabel, partialNote }: BreakdownPanelProps) {
  const [key, setKey] = useState<BreakdownKey>("department");
  const [showAll, setShowAll] = useState(false);
  const stats = key === "department" ? byDepartment : byBranch;
  const shown = showAll ? stats : stats.slice(0, SHOWN);
  const label = LABELS[key];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="group" aria-label="Group by" className="inline-flex rounded-md border border-border p-0.5 text-sm">
          {(["department", "branch"] as const).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={key === option}
              onClick={() => {
                setKey(option);
                setShowAll(false);
              }}
              className={cn(
                "rounded px-3 py-1 capitalize transition-colors duration-motion-fast",
                key === option ? "bg-primary text-on-primary" : "text-foreground-secondary hover:bg-muted",
              )}
            >
              {option}
            </button>
          ))}
        </div>
        <p className="text-xs text-foreground-muted">
          {focusLabel === "today" ? "Today" : focusLabel} · lowest attendance first
        </p>
      </div>

      {stats.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-foreground-secondary">
          No attendance records on this day to group by {label.one}.
        </p>
      ) : stats.length === 1 ? (
        <p className="rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-foreground-secondary">
          Everyone is in one {label.one} ({stats[0].name}), so there is nothing to compare.
        </p>
      ) : (
        <ul className="space-y-2">
          {shown.map((stat) => {
            const selected = (key === "department" ? active.department : active.branch) === stat.name;
            return <Row key={stat.name} stat={stat} selected={selected} label={label.one} onClick={() => onSelect(key, stat.name)} />;
          })}
        </ul>
      )}

      {stats.length > SHOWN ? (
        <Button type="button" size="sm" variant="ghost" onClick={() => setShowAll((open) => !open)}>
          {showAll ? "Show fewer" : `Show all ${stats.length} ${label.many}`}
        </Button>
      ) : null}
      {partialNote ? <p className="text-xs text-foreground-muted">{partialNote}</p> : null}
    </div>
  );
}
