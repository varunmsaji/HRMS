"use client";

import { CalendarDays, CalendarRange, Columns3, List, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { usePermissions } from "@/lib/auth/use-permissions";
import { cn } from "@/lib/utils";

import { useRosterSwapBadge } from "./roster-context";

export const SCHEDULE_VIEWS = [
  { key: "week", href: "/app/rosters/schedule/week", label: "Week", hint: "Everyone, one week", icon: CalendarRange },
  { key: "month", href: "/app/rosters/schedule/month", label: "Month", hint: "One employee, one month", icon: CalendarDays },
  { key: "day", href: "/app/rosters/schedule/day", label: "Day", hint: "Shift board for one day", icon: Columns3 },
  { key: "list", href: "/app/rosters/schedule/list", label: "List", hint: "Entries you can edit", icon: List },
] as const satisfies readonly { key: string; href: string; label: string; hint: string; icon: LucideIcon }[];

export type ScheduleViewKey = (typeof SCHEDULE_VIEWS)[number]["key"];

export const COVERAGE_HREF = "/app/rosters/coverage";
const LAST_VIEW_KEY = "roster:last-view";

export function readLastView(): ScheduleViewKey {
  try {
    const stored = window.localStorage.getItem(LAST_VIEW_KEY);
    if (SCHEDULE_VIEWS.some((v) => v.key === stored)) return stored as ScheduleViewKey;
  } catch {
    // Storage can be blocked; the default view is fine.
  }
  return "week";
}

function rememberView(key: ScheduleViewKey) {
  try {
    window.localStorage.setItem(LAST_VIEW_KEY, key);
  } catch {
    // Remembering the view is a convenience only.
  }
}

/** Where "Shift Rosters" and "Schedule" lead: the view you used last, Week the first time. */
export function lastViewHref(): string {
  const key = readLastView();
  return SCHEDULE_VIEWS.find((v) => v.key === key)?.href ?? SCHEDULE_VIEWS[0].href;
}

/** The one navigation for Shift Rosters. Two destinations — Coverage (the overview) and Schedule
 * (who works when) — and, inside Schedule, one switcher for the four ways to look at it. Staff
 * who cannot manage rosters only have Coverage (their swap requests), so they see no nav at all. */
export function RosterNav() {
  const pathname = usePathname() ?? "";
  const { can } = usePermissions();
  const { pendingSwaps } = useRosterSwapBadge();
  const canManage = can("ATTENDANCE.ROSTER_MANAGE");
  const activeView = SCHEDULE_VIEWS.find((v) => pathname.startsWith(v.href));
  const inCoverage = pathname.startsWith(COVERAGE_HREF);

  useEffect(() => {
    if (activeView) rememberView(activeView.key);
  }, [activeView]);

  if (!canManage) return null;

  const pill = (active: boolean) =>
    cn(
      "inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-medium transition-colors",
      active ? "bg-primary text-primary-foreground shadow-elevation-1" : "text-foreground-secondary hover:text-foreground",
    );

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <nav aria-label="Shift rosters" className="inline-flex rounded-full border border-border bg-surface-secondary p-1">
        <Link href={COVERAGE_HREF} aria-current={inCoverage ? "page" : undefined} className={pill(inCoverage)}>
          Coverage
          {pendingSwaps > 0 ? (
            <span
              className={cn(
                "rounded-full px-1.5 text-[11px] font-semibold tabular-nums",
                inCoverage ? "bg-primary-foreground/20 text-primary-foreground" : "bg-warning-subtle text-warning",
              )}
              title={`${pendingSwaps} swap ${pendingSwaps === 1 ? "request is" : "requests are"} waiting`}
            >
              {pendingSwaps}
              <span className="sr-only"> swap requests waiting</span>
            </span>
          ) : null}
        </Link>
        <Link
          href={lastViewHref()}
          aria-current={activeView ? "page" : undefined}
          className={pill(Boolean(activeView))}
        >
          Schedule
        </Link>
      </nav>

      {activeView ? (
        <nav aria-label="Schedule views" className="inline-flex rounded-full border border-border bg-surface p-1 shadow-elevation-1">
          {SCHEDULE_VIEWS.map((v) => {
            const Icon = v.icon;
            const active = v.key === activeView.key;
            return (
              <Link
                key={v.key}
                href={v.href}
                title={v.hint}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors",
                  active ? "bg-primary-subtle text-primary" : "text-foreground-secondary hover:bg-muted hover:text-foreground",
                )}
              >
                <Icon className="size-4" aria-hidden="true" />
                {v.label}
              </Link>
            );
          })}
        </nav>
      ) : null}
    </div>
  );
}
