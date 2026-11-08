"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  NAV_ITEMS,
  SETTINGS_MODULES,
  SETTINGS_NAV_GROUPS,
  settingsModuleFor,
  settingsModuleHref,
} from "@/components/layout/nav-items";

interface Crumb {
  label: string;
  href?: string;
}

function resolveBreadcrumbs(pathname: string | null): Crumb[] {
  if (!pathname || pathname === "/app/dashboard" || pathname === "/app") {
    return [{ label: "Dashboard" }];
  }

  // Settings module pages: /app/settings/<module>
  const moduleMatch = SETTINGS_MODULES.find((m) => pathname === settingsModuleHref(m.slug));
  if (moduleMatch) {
    return [{ label: "Settings", href: "/app/settings" }, { label: moduleMatch.label }];
  }

  // Check if path belongs to a Settings screen
  for (const group of SETTINGS_NAV_GROUPS) {
    for (const item of group.items) {
      const owner = settingsModuleFor(item.href);
      const parent: Crumb[] = owner
        ? [
            { label: "Settings", href: "/app/settings" },
            { label: owner.label, href: settingsModuleHref(owner.slug) },
          ]
        : [{ label: "Settings", href: "/app/settings" }];
      if (pathname === item.href) {
        return [...parent, { label: item.label }];
      }
      if (pathname.startsWith(`${item.href}/`)) {
        const subSegment = pathname.slice(item.href.length + 1);
        const subLabel =
          subSegment === "setup"
            ? "Guided Setup"
            : subSegment === "calendar"
              ? "Calendar"
              : "Details";
        return [...parent, { label: item.label, href: item.href }, { label: subLabel }];
      }
    }
  }

  // Check primary nav items (longest prefix first so /app/me/calendar matches before /app/me)
  const sortedPrimary = [...NAV_ITEMS].sort((a, b) => b.href.length - a.href.length);
  for (const item of sortedPrimary) {
    if (pathname === item.href) {
      return [{ label: item.label }];
    }
    if (pathname.startsWith(`${item.href}/`)) {
      const rest = pathname.slice(item.href.length + 1);
      if (rest === "calendar") {
        return [{ label: item.label, href: item.href }, { label: "Calendar View" }];
      }
      if (rest.startsWith("employee/")) {
        return [{ label: item.label, href: item.href }, { label: "Employee Attendance" }];
      }
      if (rest.includes("/payslips/")) {
        return [{ label: item.label, href: item.href }, { label: "Payslip" }];
      }
      return [{ label: item.label, href: item.href }, { label: "Details" }];
    }
  }

  return [];
}

export function AppBreadcrumbs() {
  const pathname = usePathname();
  const crumbs = resolveBreadcrumbs(pathname);

  if (crumbs.length === 0) return null;

  return (
    <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-1.5 text-xs sm:flex lg:hidden xl:flex">
      <ol className="flex min-w-0 items-center gap-1.5">
        {crumbs.map((crumb, idx) => {
          const isLast = idx === crumbs.length - 1;
          return (
            <li
              key={`${crumb.label}-${idx}`}
              className={`flex items-center gap-1.5 whitespace-nowrap ${isLast ? "shrink-0" : "min-w-0"}`}
            >
              {idx > 0 ? (
                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-foreground-disabled" aria-hidden="true" />
              ) : null}
              {crumb.href && !isLast ? (
                <Link
                  href={crumb.href}
                  className="truncate font-medium text-foreground-muted transition-colors hover:text-foreground"
                >
                  {crumb.label}
                </Link>
              ) : (
                <span
                  aria-current={isLast ? "page" : undefined}
                  className={isLast ? "max-w-[14rem] truncate font-semibold text-foreground" : "truncate text-foreground-muted"}
                >
                  {crumb.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
