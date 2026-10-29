"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { PRIMARY_NAV_GROUPS, SETTINGS_ITEMS } from "@/components/layout/nav-items";
import { useAuth } from "@/lib/auth/auth-context";
import { cn } from "@/lib/utils";

const SETTINGS_HREFS = new Set(SETTINGS_ITEMS.map((item) => item.href));

function matchesHref(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  if (href === "/app/me") {
    return pathname === "/app/me";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { user } = useAuth();
  const hasEmployeeId = Boolean(user?.employee_id);

  const activeSettingsItem = SETTINGS_ITEMS.find((item) => matchesHref(pathname, item.href));

  return (
    <nav className="flex flex-col gap-5 px-3 py-4" aria-label="Primary">
      {PRIMARY_NAV_GROUPS.map((group) => {
        const visibleItems = group.items.filter(
          (item) => !item.requiresEmployeeId || hasEmployeeId,
        );
        if (visibleItems.length === 0) return null;

        return (
          <div key={group.label} className="space-y-1">
            <p className="px-2.5 pb-1 text-2xs font-semibold uppercase tracking-wider text-foreground-muted">
              {group.label}
            </p>
            <div className="space-y-0.5">
              {visibleItems.map((item) => {
                const isSettingsHub = item.href === "/app/settings";
                const active = isSettingsHub
                  ? matchesHref(pathname, item.href) ||
                    Array.from(SETTINGS_HREFS).some((href) => matchesHref(pathname, href))
                  : matchesHref(pathname, item.href);
                const Icon = item.icon;

                return (
                  <div key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "group relative flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors duration-motion-instant focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        active
                          ? "bg-primary-subtle font-semibold text-primary before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-r before:bg-primary"
                          : "font-medium text-foreground-secondary hover:bg-muted/70 hover:text-foreground",
                      )}
                    >
                      <Icon
                        className={cn(
                          "h-4 w-4 shrink-0 transition-colors",
                          active
                            ? "text-primary"
                            : "text-foreground-muted group-hover:text-foreground-secondary",
                        )}
                        aria-hidden="true"
                      />
                      <span className="truncate">{item.label}</span>
                    </Link>

                    {isSettingsHub && activeSettingsItem ? (
                      <div className="ml-4 mt-0.5 border-l border-border pl-2.5">
                        <Link
                          href={activeSettingsItem.href}
                          onClick={onNavigate}
                          className="flex items-center gap-2 rounded-sm px-2 py-1 text-xs font-medium text-primary hover:bg-primary-subtle/60"
                        >
                          <activeSettingsItem.icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                          <span className="truncate">{activeSettingsItem.label}</span>
                        </Link>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </nav>
  );
}
