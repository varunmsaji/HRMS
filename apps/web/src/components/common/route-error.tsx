"use client";

import { useEffect } from "react";

import { ErrorState } from "@/components/common/error-state";
import { errorReference, isApiError } from "@/lib/api/errors";

export interface RouteErrorProps {
  error: Error & { digest?: string };
  /** Re-fetches and re-renders the segment (preferred). */
  retry?: () => void;
  /** Re-renders without re-fetching. Used only when `retry` is not provided. */
  reset?: () => void;
}

/**
 * The text shown for an error that escaped a page. An API failure already carries a safe,
 * user-facing message; anything else (a rendering bug, a thrown `TypeError`) never shows its own
 * message — it may hold internal details — only a generic line.
 */
export function routeErrorMessage(error: unknown): string {
  if (isApiError(error)) return error.message;
  return "This page ran into an unexpected problem. Try again, or reload the page.";
}

/** What support needs to find the failure: the API request id, or Next's server-error digest. */
export function routeErrorReference(error: Error & { digest?: string }): string | null {
  return errorReference(error) ?? error.digest ?? null;
}

export function RouteError({ error, retry, reset }: RouteErrorProps) {
  useEffect(() => {
    // Development aid only. No telemetry is sent anywhere (no third-party error service has
    // been approved), and production builds stay quiet.
    if (process.env.NODE_ENV !== "production") console.error(error);
  }, [error]);

  const reference = routeErrorReference(error);
  const message = routeErrorMessage(error);
  return (
    <div className="mx-auto w-full max-w-xl px-4 py-10">
      <ErrorState
        title="Something went wrong"
        message={reference ? `${message} Reference: ${reference}` : message}
        onRetry={retry ?? reset}
      />
    </div>
  );
}
