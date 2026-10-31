"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { EMPLOYEE_NAV_ITEMS, PRIMARY_NAV_GROUPS, SETTINGS_ITEMS } from "@/components/layout/nav-items";
import { useAuth } from "@/lib/auth/auth-context";
import { useEmployeeMode } from "@/lib/auth/use-employee-mode";
import { cn } from "@/lib/utils";

const SETTINGS_HREFS = new Set(SETTINGS_ITEMS.map((item) => item.href));

function matchesHref(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  if (href === "/app/me" || href === "/app/dashboard") {
    return pathname === href;
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { user } = useAuth();
  const hasEmployeeId = Boolean(user?.employee_id);

  const employeeMode = useEmployeeMode();

  if (employeeMode) {
    // Longest match wins so /app/me/calendar highlights My Calendar, not My Profile.
    const activeHref = EMPLOYEE_NAV_ITEMS.filter((i) => matchesHref(pathname, i.href)).sort(
      (a, b) => b.href.length - a.href.length,
    )[0]?.href;
    return (
      <nav className="flex flex-col gap-1.5 px-4 py-4" aria-label="Primary">
        {EMPLOYEE_NAV_ITEMS.map((item) => {
          const active = item.href === activeHref;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-full px-4 py-2.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                active
                  ? "bg-[#00c2ff] font-semibold text-[#06204d]"
                  : "font-medium text-slate-200 hover:bg-white/5 hover:text-white",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="truncate">{item.label}</span>
            </Link>
          );
        })}
      </nav>
    );
  }

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
            <p className="px-2.5 pb-1 text-2xs font-semibold uppercase tracking-wider text-slate-500">
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
                        "group relative flex items-center gap-2.5 rounded-full px-3 py-2 text-sm transition-colors duration-motion-instant focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        active
                          ? "bg-[#00c2ff] font-semibold text-[#06204d]"
                          : "font-medium text-slate-300 hover:bg-white/5 hover:text-white",
                      )}
                    >
                      <Icon
                        className={cn(
                          "h-4 w-4 shrink-0 transition-colors",
                          active
                            ? "text-[#06204d]"
                            : "text-slate-400 group-hover:text-slate-200",
                        )}
                        aria-hidden="true"
                      />
                      <span className="truncate">{item.label}</span>
                    </Link>

                    {isSettingsHub && activeSettingsItem ? (
                      <div className="ml-4 mt-0.5 border-l border-white/10 pl-2.5">
                        <Link
                          href={activeSettingsItem.href}
                          onClick={onNavigate}
                          className="flex items-center gap-2 rounded-sm px-2 py-1 text-xs font-medium text-blue-300 hover:bg-white/5"
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
