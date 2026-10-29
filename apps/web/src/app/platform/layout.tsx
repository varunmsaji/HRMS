"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useSyncExternalStore, type ReactNode } from "react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { loadPlatformSession, platformApi } from "@/lib/platform/api";
import { cn } from "@/lib/utils";

function subscribeNever(): () => void {
  return () => {};
}

const PLATFORM_NAV = [
  { href: "/platform", label: "Dashboard", exact: true },
  { href: "/platform/companies", label: "Companies" },
  { href: "/platform/admins", label: "Platform admins" },
  { href: "/platform/audit", label: "Audit log" },
  { href: "/platform/emails", label: "Emails" },
  { href: "/platform/logs", label: "System logs" },
];

/** Platform console shell. Deliberately independent of the tenant `AppShell` / `AuthProvider`:
 * a platform session is a different identity and shares nothing with a company login. */
export default function PlatformLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isLogin = pathname === "/platform/login";
  const username = useSyncExternalStore(
    subscribeNever,
    () => loadPlatformSession()?.username ?? null,
    () => null,
  );

  useEffect(() => {
    if (!isLogin && !loadPlatformSession()) router.replace("/platform/login");
  }, [isLogin, pathname, router]);

  if (isLogin) return <>{children}</>;
  if (!username) return null;

  async function signOut() {
    try {
      await platformApi.logout();
    } finally {
      router.replace("/platform/login");
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-4 border-b border-border bg-surface px-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-6">
          <Link
            href="/platform"
            className="flex shrink-0 items-center gap-2 text-sm font-semibold text-primary"
          >
            <Logo size={26} />
            <span className="rounded border border-border bg-surface-secondary px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-foreground-muted">
              Platform
            </span>
          </Link>
          <nav className="flex items-center gap-1 overflow-x-auto text-sm" aria-label="Platform">
            {PLATFORM_NAV.map((item) => {
              const active = item.exact
                ? pathname === item.href
                : pathname === item.href || pathname?.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "shrink-0 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    active
                      ? "bg-primary-subtle font-semibold text-primary"
                      : "text-foreground-secondary hover:bg-muted hover:text-foreground",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
        <div className="flex shrink-0 items-center gap-3 text-xs">
          <span className="font-mono text-foreground-secondary">{username}</span>
          <Button variant="outline" size="xs" onClick={() => void signOut()}>
            Sign out
          </Button>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">{children}</main>
    </div>
  );
}
