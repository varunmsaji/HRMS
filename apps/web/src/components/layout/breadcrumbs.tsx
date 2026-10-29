"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS, SETTINGS_NAV_GROUPS } from "@/components/layout/nav-items";

interface Crumb {
  label: string;
  href?: string;
}

function resolveBreadcrumbs(pathname: string | null): Crumb[] {
  if (!pathname || pathname === "/app/dashboard" || pathname === "/app") {
    return [{ label: "Dashboard" }];
  }

  // Check if path belongs to a Settings module
  for (const group of SETTINGS_NAV_GROUPS) {
    for (const item of group.items) {
      if (pathname === item.href) {
        return [
          { label: "Settings", href: "/app/settings" },
          { label: group.label, href: "/app/settings" },
          { label: item.label },
        ];
      }
      if (pathname.startsWith(`${item.href}/`)) {
        const subSegment = pathname.slice(item.href.length + 1);
        const subLabel =
          subSegment === "setup"
            ? "Guided Setup"
            : subSegment === "calendar"
              ? "Calendar"
              : "Details";
        return [
          { label: "Settings", href: "/app/settings" },
          { label: item.label, href: item.href },
          { label: subLabel },
        ];
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
    <nav aria-label="Breadcrumb" className="hidden items-center gap-1.5 text-xs sm:flex">
      <ol className="flex items-center gap-1.5">
        {crumbs.map((crumb, idx) => {
          const isLast = idx === crumbs.length - 1;
          return (
            <li key={`${crumb.label}-${idx}`} className="flex items-center gap-1.5">
              {idx > 0 ? (
                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-foreground-disabled" aria-hidden="true" />
              ) : null}
              {crumb.href && !isLast ? (
                <Link
                  href={crumb.href}
                  className="font-medium text-foreground-muted transition-colors hover:text-foreground"
                >
                  {crumb.label}
                </Link>
              ) : (
                <span
                  aria-current={isLast ? "page" : undefined}
                  className={isLast ? "font-semibold text-foreground" : "text-foreground-muted"}
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
