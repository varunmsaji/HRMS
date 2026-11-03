"use client";

import { ArrowUpRight, BookOpen, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import { SETTINGS_NAV_GROUPS } from "@/components/layout/nav-items";
import { Input } from "@/components/ui/input";

const ITEM_DESCRIPTIONS: Record<string, string> = {
  "/app/company": "Name, registration and contact details",
  "/app/legal-entities": "Legal entities that employ your people",
  "/app/branches": "Offices and locations",
  "/app/departments": "Teams and reporting structure",
  "/app/designations": "Job titles across the company",
  "/app/grades": "Levels and pay bands",
  "/app/shifts": "Working hours and shift timings",
  "/app/attendance-periods": "Open and lock attendance months",
  "/app/work-calendars": "Working days per location or team",
  "/app/holiday-calendars": "Public and company holidays",
  "/app/weekly-off-patterns": "Weekly rest-day rules",
  "/app/attendance-policies": "Late, early-exit and absence rules",
  "/app/overtime-policies": "Overtime eligibility and rates",
  "/app/regularization-policies": "Rules for correcting attendance",
  "/app/leave-types": "Casual, sick, earned and more",
  "/app/leave-policies": "Accrual, carry-forward and limits",
  "/app/leave-combination-rules": "Which leaves can be taken together",
  "/app/leave-year-setting": "When your leave year starts",
  "/app/statutory-leave-minimums": "Legal minimum leave entitlements",
  "/app/payroll/salary-components": "Earnings and deductions",
  "/app/payroll/salary-structures": "Component bundles per grade",
  "/app/payroll/statutory-rates": "PF, ESI and tax rates",
  "/app/policy-assignments": "Assign policies by scope",
  "/app/policy-resolution": "See which policy applies to whom",
  "/app/setup": "Initial setup checklist",
  "/app/users": "Accounts, roles and access",
};

export default function SettingsPage() {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();

  const groups = useMemo(
    () =>
      SETTINGS_NAV_GROUPS.map((group) => ({
        ...group,
        items: group.items.filter((item) => {
          if (!q) return true;
          const hay = `${item.label} ${ITEM_DESCRIPTIONS[item.href] ?? ""} ${group.label}`;
          return hay.toLowerCase().includes(q);
        }),
      })).filter((group) => group.items.length > 0),
    [q],
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Set up your organisation, time and leave rules, payroll, and who can access what."
        actions={
          <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
            <Link
              href="/app/settings/guide"
              className="inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium text-foreground-secondary transition-colors hover:border-primary/40 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <BookOpen className="h-4 w-4" aria-hidden="true" />
              Settings guide
            </Link>
            <div className="relative w-full sm:w-72">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted"
                aria-hidden="true"
              />
              <Input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search settings…"
                aria-label="Search settings"
                className="pl-9"
              />
            </div>
          </div>
        }
      />

      <div className="grid gap-8 lg:grid-cols-[14rem_minmax(0,1fr)]">
        <nav
          aria-label="Settings categories"
          className="hidden lg:sticky lg:top-6 lg:block lg:self-start"
        >
          <ul className="space-y-2">
            {groups.map((group) => (
              <li key={group.label}>
                <a
                  href={`#${slug(group.label)}`}
                  className="flex items-center justify-between rounded-lg border border-border bg-card px-3 py-2.5 text-sm font-medium text-foreground-secondary transition-colors hover:border-primary/40 hover:bg-primary-subtle hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span>{group.label}</span>
                  <span className="rounded-full border border-border bg-muted/60 px-2 py-0.5 text-xs text-foreground-muted">
                    {group.items.length}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="space-y-10">
          {groups.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border px-6 py-12 text-center text-sm text-foreground-secondary">
              No settings match “{query}”.
            </p>
          ) : null}

          {groups.map((group) => (
            <section
              key={group.label}
              id={slug(group.label)}
              aria-labelledby={`${slug(group.label)}-title`}
              className="scroll-mt-6"
            >
              <div className="mb-3">
                <h2
                  id={`${slug(group.label)}-title`}
                  className="text-md font-semibold text-foreground"
                >
                  {group.label}
                </h2>
                {group.description ? (
                  <p className="mt-0.5 text-sm text-foreground-secondary">
                    {group.description}
                  </p>
                ) : null}
              </div>

              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const description = ITEM_DESCRIPTIONS[item.href];
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className="group relative flex items-start gap-3 rounded-lg border border-border bg-card p-4 transition-all duration-motion-instant hover:border-primary/40 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-foreground-secondary transition-colors group-hover:bg-primary/10 group-hover:text-primary">
                        <Icon className="h-4 w-4" aria-hidden="true" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-foreground">
                          {item.label}
                        </span>
                        {description ? (
                          <span className="mt-0.5 block text-xs text-foreground-secondary">
                            {description}
                          </span>
                        ) : null}
                      </span>
                      <ArrowUpRight
                        className="h-4 w-4 shrink-0 text-foreground-disabled opacity-0 transition-opacity group-hover:opacity-100"
                        aria-hidden="true"
                      />
                    </Link>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

function slug(label: string) {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}
