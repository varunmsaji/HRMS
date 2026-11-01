"use client";

import { ChevronDown, LogOut, Menu, Search, User } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { NotificationBell } from "@/components/notifications/notification-bell";
import { useToast } from "@/components/common/toast";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import type { Employee } from "@/lib/employee/types";

/** Personal-view top bar: search, notifications, and the signed-in person's name and role. */
export function EmployeeTopBar({ onOpenNav }: { onOpenNav: () => void }) {
  const router = useRouter();
  const { user, logout } = useAuth();
  const { toast } = useToast();
  const [name, setName] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const employeeId = user?.employee_id ?? null;
  useEffect(() => {
    if (!employeeId) return;
    let cancelled = false;
    apiClient
      .get<Employee>(`/employees/${employeeId}`)
      .then((e) => {
        if (!cancelled) setName(e.display_name ?? e.first_name);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [employeeId]);

  function onSearch(e: FormEvent) {
    e.preventDefault();
    const q = query.trim().toLowerCase();
    if (!q) return;
    const target = q.includes("pay")
      ? "/app/me/payslips"
      : q.includes("leave")
        ? "/app/leave-applications"
        : q.includes("correct") || q.includes("regular")
          ? "/app/regularizations"
          : "/app/attendance";
    router.push(target);
  }

  async function handleLogout() {
    await logout();
    toast({ title: "Signed out" });
    router.push("/login");
  }

  const label = name ?? user?.email ?? "Account";

  return (
    <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center justify-between gap-4 bg-surface/95 px-4 shadow-elevation-1 backdrop-blur sm:px-8 print:hidden">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <button
          type="button"
          onClick={onOpenNav}
          aria-label="Open navigation"
          className="flex h-9 w-9 items-center justify-center rounded-md text-foreground-secondary hover:bg-muted md:hidden"
        >
          <Menu className="h-4 w-4" aria-hidden="true" />
        </button>
        <form onSubmit={onSearch} role="search" className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted" aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search leave, attendance, payslips..."
            aria-label="Search"
            className="h-10 w-full rounded-lg bg-muted pl-9 pr-3 text-sm text-foreground placeholder:text-foreground-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </form>
      </div>

      <div className="flex items-center gap-4">
        <NotificationBell />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label="Account menu"
              className="flex items-center gap-3 rounded-lg px-1 py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="hidden border-l border-border pl-4 text-right sm:block">
                <span className="block text-sm font-semibold leading-tight text-foreground">{label}</span>
                <span className="block text-2xs font-semibold text-foreground-muted">Employee</span>
              </span>
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#0b1d4d] text-white">
                <User className="h-4 w-4" aria-hidden="true" />
              </span>
              <ChevronDown className="hidden h-3.5 w-3.5 text-foreground-muted sm:block" aria-hidden="true" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuItem asChild>
              <Link href="/app/me" className="cursor-pointer">
                <User className="h-4 w-4" aria-hidden="true" />
                My Profile
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={handleLogout} className="text-danger focus:text-danger">
              <LogOut className="h-4 w-4" aria-hidden="true" />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
