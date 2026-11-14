"use client";

import { CircleCheck, Info, TriangleAlert, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

type ToastVariant = "default" | "success" | "warning" | "danger" | "info";

interface ToastItem {
  id: string;
  title: string;
  description?: string;
  variant: ToastVariant;
}

interface ToastInput {
  title: string;
  description?: string;
  variant?: ToastVariant;
}

interface ToastContextValue {
  toast: (input: ToastInput) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);
const AUTO_DISMISS_MS = 5000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback(
    (input: ToastInput) => {
      const id = `toast_${Date.now()}_${Math.random().toString(16).slice(2)}`;
      setToasts((current) => [...current, { id, variant: "default", ...input }]);
      window.setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss],
  );

  // Stable, so consumers can depend on it in effects without re-running them on every toast.
  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4 sm:inset-x-auto sm:right-4 sm:items-end">
        {toasts.map((item) => (
          <div
            key={item.id}
            role="status"
            className={cn(
              "pointer-events-auto flex w-full max-w-sm items-start gap-2.5 rounded-lg border bg-surface p-3.5 shadow-elevation-2",
              item.variant === "danger" && "border-danger-border",
              item.variant === "warning" && "border-warning-border",
              item.variant === "success" && "border-success-border",
              item.variant === "info" && "border-info-border",
              item.variant === "default" && "border-border",
            )}
          >
            {item.variant === "success" ? (
              <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
            ) : null}
            {item.variant === "danger" || item.variant === "warning" ? (
              <TriangleAlert
                className={cn(
                  "mt-0.5 h-4 w-4 shrink-0",
                  item.variant === "danger" ? "text-danger" : "text-warning",
                )}
                aria-hidden="true"
              />
            ) : null}
            {item.variant === "info" ? (
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-info" aria-hidden="true" />
            ) : null}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-foreground">{item.title}</p>
              {item.description ? (
                <p className="mt-0.5 text-xs leading-relaxed text-foreground-secondary">
                  {item.description}
                </p>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => dismiss(item.id)}
              className="rounded-sm p-0.5 text-foreground-muted transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Dismiss notification"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}

/** For components that may render outside a `ToastProvider` (e.g. in isolated tests): no-op then. */
export function useOptionalToast(): ToastContextValue | null {
  return useContext(ToastContext);
}
