"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS, SETTINGS_ITEMS } from "@/components/layout/nav-items";
import { useAuth } from "@/lib/auth/auth-context";
import { cn } from "@/lib/utils";

const SETTINGS_HREFS = new Set(SETTINGS_ITEMS.map((item) => item.href));

function matchesHref(pathname: string | null, href: string): boolean {
  return pathname === href || Boolean(pathname?.startsWith(`${href}/`));
}

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { user } = useAuth();
  const items = NAV_ITEMS.filter((item) => !item.requiresEmployeeId || Boolean(user?.employee_id));

  return (
    <nav className="flex flex-col gap-1 p-3" aria-label="Primary">
      {items.map((item) => {
        // "Settings" also lights up while on any of the config pages it links out to, so the
        // sidebar still shows where you are even though those pages aren't listed directly.
        const active =
          item.href === "/app/settings"
            ? matchesHref(pathname, item.href) ||
              Array.from(SETTINGS_HREFS).some((href) => matchesHref(pathname, href))
            : matchesHref(pathname, item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              active
                ? "bg-primary-subtle text-primary"
                : "text-foreground-secondary hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4" aria-hidden="true" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
