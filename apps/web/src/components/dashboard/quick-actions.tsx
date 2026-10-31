"use client";

import { CalendarClock, Clock, Palmtree, UserPlus, UserRoundPlus, Users, type LucideIcon } from "lucide-react";
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

export function QuickActions() {
  const { canAny } = usePermissions();
  const visible = ACTIONS.filter((a) => a.anyOf.length === 0 || canAny(a.anyOf));
  if (visible.length === 0) return null;
  return (
    <section aria-label="Quick actions">
      <h2 className="mb-3 text-base font-semibold text-foreground">Quick actions</h2>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {visible.map((a) => {
          const Icon = a.icon;
          return (
            <li key={a.label} className="min-w-0">
              <Link
                href={a.href}
                className="flex h-full items-center gap-2.5 rounded-lg border border-border bg-surface px-3 py-2.5 text-sm font-medium text-foreground hover:border-border-strong hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Icon className="h-4 w-4 shrink-0 text-foreground-secondary" aria-hidden="true" />
                <span className="truncate">{a.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
