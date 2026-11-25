"use client";

import type { ReactNode } from "react";

import { ClientErrorListener } from "@/components/common/client-error-listener";
import { ToastProvider } from "@/components/common/toast";
import { AuthProvider } from "@/lib/auth/auth-context";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ToastProvider>
      <ClientErrorListener />
      <AuthProvider>{children}</AuthProvider>
    </ToastProvider>
  );
}
