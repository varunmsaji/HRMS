"use client";

import {
  BadgeIndianRupee,
  Banknote,
  Briefcase,
  CalendarClock,
  FileText,
  GraduationCap,
  IdCard,
  Landmark,
  LayoutGrid,
  Network,
  ScrollText,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

import { TabBar } from "@/components/ui/tab-bar";
import { cn } from "@/lib/utils";

export type EmployeeSectionKey =
  | "overview"
  | "employment"
  | "assignment"
  | "compensation"
  | "salary"
  | "statutory"
  | "banking"
  | "identity"
  | "experience"
  | "education"
  | "dependents"
  | "documents"
  | "attendance";

interface SectionItem {
  key: EmployeeSectionKey;
  label: string;
  icon: LucideIcon;
}

export const EMPLOYEE_SECTION_GROUPS: ReadonlyArray<{ label: string; items: SectionItem[] }> = [
  {
    label: "Profile",
    items: [
      { key: "overview", label: "Overview", icon: LayoutGrid },
      { key: "identity", label: "Identity", icon: IdCard },
      { key: "experience", label: "Experience", icon: Briefcase },
      { key: "education", label: "Education", icon: GraduationCap },
      { key: "dependents", label: "Dependents", icon: Users },
      { key: "documents", label: "Documents", icon: FileText },
    ],
  },
  {
    label: "Work",
    items: [
      { key: "employment", label: "Employment", icon: ScrollText },
      { key: "assignment", label: "Assignment", icon: Network },
      { key: "attendance", label: "Attendance", icon: CalendarClock },
    ],
  },
  {
    label: "Pay",
    items: [
      { key: "compensation", label: "Compensation", icon: BadgeIndianRupee },
      { key: "salary", label: "Salary", icon: Wallet },
      { key: "statutory", label: "Statutory", icon: Landmark },
      { key: "banking", label: "Banking", icon: Banknote },
    ],
  },
];

const ALL_SECTIONS = EMPLOYEE_SECTION_GROUPS.flatMap((group) => group.items);

export function isEmployeeSection(value: string | null): value is EmployeeSectionKey {
  return ALL_SECTIONS.some((item) => item.key === value);
}

/** A grouped side menu on wide screens; the app's standard tab strip on narrow ones. */
export function EmployeeSectionNav({
  value,
  onChange,
}: {
  value: EmployeeSectionKey;
  onChange: (key: EmployeeSectionKey) => void;
}) {
  return (
    <>
      <TabBar
        tabs={ALL_SECTIONS}
        value={value}
        onChange={onChange}
        label="Employee profile sections"
        className="lg:hidden"
      />
      <nav
        aria-label="Employee profile sections"
        className="hidden lg:sticky lg:top-4 lg:block lg:self-start"
      >
        <div className="space-y-5 rounded-2xl border border-border bg-surface p-3 shadow-elevation-1">
          {EMPLOYEE_SECTION_GROUPS.map((group) => (
            <div key={group.label}>
              <p className="px-2.5 pb-1.5 text-2xs font-semibold uppercase tracking-wider text-foreground-muted">
                {group.label}
              </p>
              <ul className="space-y-0.5">
                {group.items.map((item) => {
                  const selected = item.key === value;
                  const Icon = item.icon;
                  return (
                    <li key={item.key}>
                      <button
                        type="button"
                        aria-current={selected ? "page" : undefined}
                        onClick={() => onChange(item.key)}
                        className={cn(
                          "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm font-medium transition-colors duration-motion-instant focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          selected
                            ? "bg-primary-subtle text-primary"
                            : "text-foreground-secondary hover:bg-surface-secondary hover:text-foreground",
                        )}
                      >
                        <Icon
                          className={cn("h-4 w-4 shrink-0", selected ? "text-primary" : "text-foreground-muted")}
                          aria-hidden="true"
                        />
                        {item.label}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      </nav>
    </>
  );
}
