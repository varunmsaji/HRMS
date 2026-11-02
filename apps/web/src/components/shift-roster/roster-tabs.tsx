import Link from "next/link";

import { cn } from "@/lib/utils";

const TABS = [
  { href: "/app/rosters/schedule", key: "coverage", label: "Schedule coverage" },
  { href: "/app/rosters", key: "entries", label: "Roster entries" },
  { href: "/app/rosters/calendar", key: "calendar", label: "Calendar" },
  { href: "/app/rosters/grid", key: "grid", label: "Workforce roster" },
] as const;

/** One "Shift Rosters" destination in the sidebar; this strip switches between its views. */
export function RosterTabs({ active }: { active: (typeof TABS)[number]["key"] }) {
  return (
    <nav aria-label="Shift roster views" className="flex gap-6 overflow-x-auto whitespace-nowrap border-b border-border text-sm">
      {TABS.map((tab) =>
        tab.key === active ? (
          <span key={tab.key} className="-mb-px border-b-2 border-primary pb-2.5 font-semibold text-primary" aria-current="page">
            {tab.label}
          </span>
        ) : (
          <Link key={tab.key} href={tab.href} className="pb-2.5 text-foreground-secondary hover:text-foreground">
            {tab.label}
          </Link>
        ),
      )}
    </nav>
  );
}
