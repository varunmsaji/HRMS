"use client";

import { Building2, Menu } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { CompanyContext } from "@/components/layout/company-context";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { UserMenu } from "@/components/layout/user-menu";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

function SidebarBrand() {
  return (
    <Link href="/app/dashboard" className="flex items-center gap-2.5 px-1">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-on-primary">
        <Building2 className="h-4 w-4" aria-hidden="true" />
      </div>
      <div className="flex flex-col leading-tight">
        <span className="text-sm font-semibold text-primary">Krewoxa</span>
        <span className="text-[11px] font-medium text-foreground-muted">Enterprise</span>
      </div>
    </Link>
  );
}

/** Desktop (≥1024px): persistent left sidebar + top bar, per docs/design/03_Navigation_System.md §2.
 * Below that, the sidebar collapses into a Sheet drawer opened from the top bar (§3–4). */
export function AppShell({ children }: { children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="hidden w-60 shrink-0 border-r border-border bg-surface md:block print:hidden">
        <div className="flex h-14 items-center border-b border-border px-4">
          <SidebarBrand />
        </div>
        <SidebarNav />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-surface px-4 print:hidden">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              onClick={() => setMobileNavOpen(true)}
              aria-label="Open navigation"
            >
              <Menu className="h-5 w-5" aria-hidden="true" />
            </Button>
            <CompanyContext />
          </div>
          <UserMenu />
        </header>

        <main className="flex-1 p-4 sm:p-6 lg:p-8 print:p-0">
          <div className="mx-auto w-full max-w-[1280px]">{children}</div>
        </main>
      </div>

      <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent side="left" className="w-64 p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <div className="flex h-14 items-center border-b border-border px-4">
            <SidebarBrand />
          </div>
          <SidebarNav onNavigate={() => setMobileNavOpen(false)} />
        </SheetContent>
      </Sheet>
    </div>
  );
}
