"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { AppShell } from "@/components/layout/app-shell";
import { LoadingState } from "@/components/common/loading-state";
import { useAuth } from "@/lib/auth/auth-context";

/** Guards everything under /app — unauthenticated users never see the shell, let alone its
 * content, redirected to /login instead (docs/design/00_UI_Vision.md §4 principle 8: gated
 * content is absent, not disabled-and-visible). */
export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { status } = useAuth();

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [status, router]);

  if (status === "loading") {
    return <LoadingState fullPage label="Loading your workspace…" />;
  }

  if (status === "unauthenticated") {
    return null;
  }

  return <AppShell>{children}</AppShell>;
}
