"use client";

import { ChevronDown, LogOut, Moon, Sun, User, UserCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useToast } from "@/components/common/toast";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/lib/auth/auth-context";

function getInitials(email?: string | null): string {
  if (!email) return "U";
  const local = email.split("@")[0] ?? "U";
  const parts = local.split(/[._-]/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }
  return local.slice(0, 2).toUpperCase();
}

export function UserMenu() {
  const router = useRouter();
  const { user, logout } = useAuth();
  const { toast } = useToast();
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    if (typeof window === "undefined") return "light";
    const stored = window.localStorage.getItem("hrms-theme");
    if (stored === "dark" || stored === "light") return stored;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });

  useEffect(() => {
    if (typeof document === "undefined") return;
    const stored = window.localStorage.getItem("hrms-theme");
    if (stored === "dark" || stored === "light") {
      document.documentElement.setAttribute("data-theme", stored);
    }
  }, []);

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    if (typeof document !== "undefined") {
      document.documentElement.setAttribute("data-theme", next);
      window.localStorage.setItem("hrms-theme", next);
    }
  }

  async function handleLogout() {
    await logout();
    toast({ title: "Signed out" });
    router.push("/login");
  }

  const initials = getInitials(user?.email);

  return (
    <div className="flex items-center gap-1.5">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={toggleTheme}
        aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        className="h-8 w-8 text-foreground-secondary"
      >
        {theme === "dark" ? (
          <Sun className="h-4 w-4" aria-hidden="true" />
        ) : (
          <Moon className="h-4 w-4" aria-hidden="true" />
        )}
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            aria-label="Account menu"
            className="h-8 gap-2 px-2 text-foreground hover:bg-muted"
          >
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary-subtle text-2xs font-semibold text-primary">
              {user?.email ? initials : <User className="h-3.5 w-3.5" aria-hidden="true" />}
            </span>
            {user?.email ? (
              <span className="hidden max-w-[160px] truncate text-xs font-medium text-foreground-secondary md:inline">
                {user.email}
              </span>
            ) : null}
            <ChevronDown className="hidden h-3.5 w-3.5 text-foreground-muted md:inline" aria-hidden="true" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-60">
          <DropdownMenuLabel className="font-normal">
            <div className="flex flex-col space-y-0.5">
              <p className="text-xs font-medium text-foreground">Account</p>
              <p className="truncate text-xs text-foreground-secondary">
                {user?.email ?? "Signed in"}
              </p>
            </div>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          {user?.employee_id ? (
            <DropdownMenuItem asChild>
              <Link href="/app/me" className="cursor-pointer">
                <UserCircle className="h-4 w-4" aria-hidden="true" />
                My Profile
              </Link>
            </DropdownMenuItem>
          ) : null}
          <DropdownMenuItem onSelect={toggleTheme}>
            {theme === "dark" ? (
              <Sun className="h-4 w-4" aria-hidden="true" />
            ) : (
              <Moon className="h-4 w-4" aria-hidden="true" />
            )}
            {theme === "dark" ? "Light appearance" : "Dark appearance"}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={handleLogout} className="text-danger focus:text-danger">
            <LogOut className="h-4 w-4" aria-hidden="true" />
            Sign out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
