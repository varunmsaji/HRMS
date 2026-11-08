"use client";

import { ArrowRight, BookOpen, CircleCheck, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/common/page-header";
import {
  SetupChecklistBanner,
  useSetupChecklist,
} from "@/components/company/setup-checklist-card";
import {
  SETTINGS_MODULES,
  SETTINGS_SHARED_GROUP,
  settingsModuleHref,
  type NavItem,
  type SettingsModule,
} from "@/components/layout/nav-items";
import { SETTINGS_ITEM_DESCRIPTIONS } from "@/components/settings/item-descriptions";
import { SettingsItemCard } from "@/components/settings/settings-item-card";
import { Input } from "@/components/ui/input";
import type { SetupChecklist } from "@/lib/company/setup-checklist";

function moduleItems(area: SettingsModule): NavItem[] {
  return area.sections.flatMap((section) => section.items);
}

/** "2 of 5 setup steps done", or nothing when the checklist has no steps for this module. */
function progressText(area: SettingsModule, checklist: SetupChecklist | null): {
  text: string;
  complete: boolean;
} | null {
  if (!checklist || area.checklistCodes.length === 0) return null;
  const items = checklist.items.filter((item) => area.checklistCodes.includes(item.code));
  if (items.length === 0) return null;
  const done = items.filter((item) => item.is_complete).length;
  return done === items.length
    ? { text: "Set up", complete: true }
    : { text: `${done} of ${items.length} setup steps done`, complete: false };
}

function ModuleCard({
  area,
  checklist,
}: {
  area: SettingsModule;
  checklist: SetupChecklist | null;
}) {
  const Icon = area.icon;
  const items = moduleItems(area).filter((item) => !item.advanced);
  const progress = progressText(area, checklist);
  return (
    <Link
      href={settingsModuleHref(area.slug)}
      className="group flex flex-col gap-3 rounded-lg border border-border bg-card p-5 transition-all duration-motion-instant hover:border-primary/40 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-muted text-foreground-secondary transition-colors group-hover:bg-primary/10 group-hover:text-primary">
          <Icon className="h-5 w-5" aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-md font-semibold text-foreground">{area.label}</span>
          <span className="mt-0.5 block text-sm text-foreground-secondary">{area.description}</span>
        </span>
        <ArrowRight
          className="mt-1 h-4 w-4 shrink-0 text-foreground-disabled transition-colors group-hover:text-primary"
          aria-hidden="true"
        />
      </div>
      <span className="text-xs text-foreground-muted">
        {items.map((item) => item.label).join(" · ")}
      </span>
      {progress ? (
        <span
          className={
            progress.complete
              ? "inline-flex items-center gap-1 text-xs font-medium text-success"
              : "text-xs font-medium text-warning"
          }
        >
          {progress.complete ? <CircleCheck className="h-3.5 w-3.5" aria-hidden="true" /> : null}
          {progress.text}
        </span>
      ) : null}
    </Link>
  );
}

export default function SettingsPage() {
  const [query, setQuery] = useState("");
  const checklist = useSetupChecklist();
  const q = query.trim().toLowerCase();

  // Searching lists matching screens directly, including ones tucked behind "Show more".
  const results = useMemo(() => {
    if (!q) return [];
    const groups = [
      ...SETTINGS_MODULES.map((area) => ({ label: area.label, items: moduleItems(area) })),
      { label: SETTINGS_SHARED_GROUP.label, items: SETTINGS_SHARED_GROUP.items },
    ];
    return groups
      .map((group) => ({
        ...group,
        items: group.items.filter((item) =>
          `${item.label} ${SETTINGS_ITEM_DESCRIPTIONS[item.href] ?? ""} ${group.label}`
            .toLowerCase()
            .includes(q),
        ),
      }))
      .filter((group) => group.items.length > 0);
  }, [q]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Set up your organisation, attendance and leave rules, payroll, and who can access what. Each area has everything it needs on one page."
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

      <SetupChecklistBanner checklist={checklist} />

      {q ? (
        <div className="space-y-8">
          {results.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border px-6 py-12 text-center text-sm text-foreground-secondary">
              No settings match “{query}”.
            </p>
          ) : null}
          {results.map((group) => (
            <section key={group.label} aria-label={group.label} className="space-y-3">
              <h2 className="text-md font-semibold text-foreground">{group.label}</h2>
              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
                {group.items.map((item) => (
                  <SettingsItemCard key={item.href} item={item} />
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {SETTINGS_MODULES.map((area) => (
            <ModuleCard key={area.slug} area={area} checklist={checklist} />
          ))}
        </div>
      )}
    </div>
  );
}
