"use client";

import { LogOut, Menu } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Logo } from "@/components/brand/logo";
import { AppBreadcrumbs } from "@/components/layout/breadcrumbs";
import { CompanyContext } from "@/components/layout/company-context";
import { CompanySearch } from "@/components/layout/company-search";
import { CompanyStatusBanner } from "@/components/layout/company-status-banner";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { NotificationBell } from "@/components/notifications/notification-bell";
import { NotificationsProvider } from "@/components/notifications/notifications-provider";
import { UserMenu } from "@/components/layout/user-menu";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/common/toast";
import { EmployeeTopBar } from "@/components/layout/employee-top-bar";
import { useAuth } from "@/lib/auth/auth-context";
import { useEmployeeMode } from "@/lib/auth/use-employee-mode";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

function SidebarBrand() {
  return (
    <Link
      href="/app/dashboard"
      className="flex items-center gap-2 rounded-sm px-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      aria-label="Krewoxa dashboard"
    >
      <Logo size={28} onDark />
    </Link>
  );
}

/** Always-visible sign out for every signed-in user (company admins and staff alike). */
function SidebarFooter() {
  const employeeMode = useEmployeeMode();
  if (!employeeMode) return <SidebarSignOut />;
  return (
    <div className="shrink-0 p-4">
      <div className="rounded-xl bg-white/5 p-4">
        <Logo size={14} onDark />
        <p className="mt-2 text-xs text-slate-300">People. Work. Simplified.</p>
      </div>
    </div>
  );
}

function SidebarSignOut() {
  const router = useRouter();
  const { logout } = useAuth();
  const { toast } = useToast();

  async function handleSignOut() {
    await logout();
    toast({ title: "Signed out" });
    router.push("/login");
  }

  return (
    <div className="shrink-0 border-t border-white/5 p-3">
      <button
        type="button"
        onClick={handleSignOut}
        className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium text-slate-300 transition-colors hover:bg-white/5 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <LogOut className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
        Sign out
      </button>
    </div>
  );
}

const SIDEBAR_BG = "bg-[#0b1530] text-slate-300";

/** Desktop (≥768px): persistent left sidebar + top bar, per docs/design/03_Navigation_System.md §2.
 * Below that, the sidebar collapses into a Sheet drawer opened from the top bar (§3–4). */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isDashboard = pathname === "/app/dashboard";
  const employeeMode = useEmployeeMode();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <NotificationsProvider>
    <div className="flex min-h-screen bg-background text-foreground">
      <a
        href="#main-content"
        onClick={(event) => {
          const main = document.getElementById("main-content");
          if (!main) return;
          event.preventDefault();
          main.focus();
        }}
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-3 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-1.5 focus:text-xs focus:font-semibold focus:text-on-primary focus:shadow-elevation-2"
      >
        Skip to main content
      </a>

      <aside className="hidden w-60 shrink-0 flex-col border-r border-white/5 bg-[#0b1530] text-slate-300 md:flex print:hidden">
        <div className="flex h-16 shrink-0 items-center px-5">
          <SidebarBrand />
        </div>
        <div className="flex-1 overflow-y-auto">
          <SidebarNav />
        </div>
        <SidebarFooter />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {employeeMode ? <EmployeeTopBar onOpenNav={() => setMobileNavOpen(true)} /> : null}
        {!employeeMode ? (
        <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center justify-between gap-4 bg-surface/95 px-4 shadow-elevation-1 backdrop-blur sm:px-8 print:hidden">
          <div className="flex min-w-0 items-center gap-3">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 md:hidden"
              onClick={() => setMobileNavOpen(true)}
              aria-label="Open navigation"
            >
              <Menu className="h-4 w-4" aria-hidden="true" />
            </Button>
            <CompanyContext />
            <div className="hidden h-4 w-px bg-border sm:block" aria-hidden="true" />
            <AppBreadcrumbs />
          </div>
          <CompanySearch />
          <div className="flex items-center gap-1.5">
            <NotificationBell />
            <UserMenu />
          </div>
        </header>
        ) : null}

        <main
          id="main-content"
          tabIndex={-1}
          className="flex-1 px-4 py-6 outline-none sm:px-6 lg:px-8 print:p-0"
        >
          <div className="mx-auto w-full max-w-[1440px]">
            <CompanyStatusBanner />
            {/* Keyed so arriving on the dashboard from any page replays the entrance; other routes
             * share one key and behave exactly as before. */}
            <div key={isDashboard ? "dashboard" : "page"} className={isDashboard ? "dashboard-enter" : undefined}>
              {children}
            </div>
          </div>
        </main>
      </div>

      <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent side="left" className={`flex w-64 flex-col border-white/5 p-0 ${SIDEBAR_BG}`}>
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <div className="flex h-16 items-center px-5">
            <SidebarBrand />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <SidebarNav onNavigate={() => setMobileNavOpen(false)} />
          </div>
          <SidebarFooter />
        </SheetContent>
      </Sheet>
    </div>
    </NotificationsProvider>
  );
}
