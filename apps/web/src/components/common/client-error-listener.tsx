"use client";

import { useEffect } from "react";

import { reportClientError } from "@/lib/observability/report-client-error";

/** Reports uncaught errors and unhandled promise rejections that no error boundary sees. Renders
 * nothing and shows the user nothing — a failed `await` with no `catch` stays invisible in the UI
 * but is no longer invisible to the developer. */
export function ClientErrorListener() {
  useEffect(() => {
    const onError = (event: ErrorEvent) => reportClientError(event.error ?? event.message, "uncaught");
    const onRejection = (event: PromiseRejectionEvent) =>
      reportClientError(event.reason, "unhandled_rejection");
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);
  return null;
}
