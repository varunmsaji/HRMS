"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useSyncExternalStore, type ReactNode } from "react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { loadPlatformSession, platformApi } from "@/lib/platform/api";

function subscribeNever(): () => void {
  return () => {};
}

/** Platform console shell. Deliberately independent of the tenant `AppShell` / `AuthProvider`:
 * a platform session is a different identity and shares nothing with a company login. */
export default function PlatformLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isLogin = pathname === "/platform/login";
  // sessionStorage is a browser-only external store: `null` on the server and during hydration,
  // re-read on every render (route changes re-render this layout).
  const username = useSyncExternalStore(
    subscribeNever,
    () => loadPlatformSession()?.username ?? null,
    () => null,
  );

  // Read the stored session directly (client-only, after hydration). Using the hydration-time
  // `username` here would redirect a signed-in user on every full page load.
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
    <div className="min-h-screen bg-background">
      <header className="flex h-14 items-center justify-between border-b border-border bg-surface px-4 sm:px-6">
        <div className="flex items-center gap-6">
          <Link href="/platform" className="flex items-center gap-2 text-sm font-semibold text-primary">
            <Logo size={26} />
            <span className="text-xs font-medium text-foreground-muted">Platform</span>
          </Link>
          <nav className="flex gap-4 text-sm">
            <Link href="/platform" className="text-foreground hover:underline">Dashboard</Link>
            <Link href="/platform/companies" className="text-foreground hover:underline">Companies</Link>
            <Link href="/platform/admins" className="text-foreground hover:underline">Platform admins</Link>
            <Link href="/platform/audit" className="text-foreground hover:underline">Audit log</Link>
            <Link href="/platform/emails" className="text-foreground hover:underline">Emails</Link>
            <Link href="/platform/logs" className="text-foreground hover:underline">System logs</Link>
          </nav>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-foreground-muted">{username}</span>
          <Button variant="outline" size="sm" onClick={signOut}>Sign out</Button>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1280px] p-4 sm:p-6 lg:p-8">{children}</main>
    </div>
  );
}
