"use client";

import { ArrowRight, CalendarClock, Clock, Palmtree, UserPlus, UserRoundPlus, Users, type LucideIcon } from "lucide-react";
import Link from "next/link";

import { usePermissions } from "@/lib/auth/use-permissions";

interface Action {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Any of these grants the shortcut; empty means always shown. */
  anyOf: string[];
}

/** Navigation shortcuts only — each opens an existing screen, which enforces its own access. */
const ACTIONS: Action[] = [
  { href: "/app/employees", label: "Add employee", icon: UserRoundPlus, anyOf: ["EMPLOYEE.CREATE"] },
  { href: "/app/onboarding", label: "Create onboarding", icon: UserPlus, anyOf: ["ONBOARDING.CREATE"] },
  { href: "/app/attendance", label: "View attendance", icon: CalendarClock, anyOf: ["ATTENDANCE.VIEW"] },
  { href: "/app/leave-applications", label: "Manage leave requests", icon: Palmtree, anyOf: ["LEAVE.APPLICATION_APPROVE"] },
  { href: "/app/shifts", label: "Manage shifts", icon: Clock, anyOf: ["ORG.SHIFT.MANAGE"] },
  { href: "/app/employees", label: "Employee directory", icon: Users, anyOf: ["EMPLOYEE.VIEW_ALL"] },
];

const TILES = [
  "bg-gradient-to-br from-blue-600 to-blue-700 text-white [&_p]:text-white/80",
  "bg-gradient-to-br from-cyan-500 to-sky-500 text-white [&_p]:text-white/80",
  "bg-surface border border-border text-foreground",
  "bg-surface border border-border text-foreground",
];

export function QuickActions() {
  const { canAny } = usePermissions();
  const visible = ACTIONS.filter((a) => a.anyOf.length === 0 || canAny(a.anyOf));
  if (visible.length === 0) return null;
  return (
    <section aria-label="Quick actions">
      <h2 className="mb-3 text-base font-semibold text-foreground">Quick actions</h2>
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {visible.slice(0, 4).map((a, i) => {
          const Icon = a.icon;
          const filled = i < 2;
          return (
            <li key={a.label} className="min-w-0">
              <Link
                href={a.href}
                className={`flex h-full items-center gap-4 rounded-2xl p-5 shadow-elevation-1 transition-shadow hover:shadow-elevation-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${TILES[i]}`}
              >
                <span
                  className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl ${filled ? "bg-white/20" : "bg-primary-subtle text-primary"}`}
                >
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </span>
                <span className="min-w-0 flex-1 truncate text-sm font-semibold">{a.label}</span>
                <ArrowRight className="h-4 w-4 shrink-0 opacity-70" aria-hidden="true" />
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
