"use client";

import { Menu } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Logo } from "@/components/brand/logo";
import { AppBreadcrumbs } from "@/components/layout/breadcrumbs";
import { CompanyContext } from "@/components/layout/company-context";
import { CompanyStatusBanner } from "@/components/layout/company-status-banner";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { UserMenu } from "@/components/layout/user-menu";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

function SidebarBrand() {
  return (
    <Link
      href="/app/dashboard"
      className="flex items-center gap-2 rounded-sm px-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      aria-label="Krewoxa dashboard"
    >
      <Logo size={26} />
      <span className="rounded border border-border bg-surface-secondary px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-foreground-muted">
        HRMS
      </span>
    </Link>
  );
}

/** Desktop (≥768px): persistent left sidebar + top bar, per docs/design/03_Navigation_System.md §2.
 * Below that, the sidebar collapses into a Sheet drawer opened from the top bar (§3–4). */
export function AppShell({ children }: { children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
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

      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-surface md:flex print:hidden">
        <div className="flex h-14 shrink-0 items-center border-b border-border px-4">
          <SidebarBrand />
        </div>
        <div className="flex-1 overflow-y-auto">
          <SidebarNav />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-surface/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-surface/90 sm:px-6 print:hidden">
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
          <UserMenu />
        </header>

        <main
          id="main-content"
          tabIndex={-1}
          className="flex-1 px-4 py-6 outline-none sm:px-6 lg:px-8 print:p-0"
        >
          <div className="mx-auto w-full max-w-[1440px]">
            <CompanyStatusBanner />
            {children}
          </div>
        </main>
      </div>

      <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent side="left" className="w-64 p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <div className="flex h-14 items-center border-b border-border px-4">
            <SidebarBrand />
          </div>
          <div className="h-[calc(100vh-3.5rem)] overflow-y-auto">
            <SidebarNav onNavigate={() => setMobileNavOpen(false)} />
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
