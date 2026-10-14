"use client";

import { routeErrorReference, type RouteErrorProps } from "@/components/common/route-error";

/**
 * Last-resort boundary for a failure in the root layout itself. It replaces the whole document,
 * so it renders its own `<html>`/`<body>` and cannot rely on the app's global styles; inline
 * styles keep it legible on desktop and mobile. Never shows the error's own message.
 */
export default function GlobalError({ error, retry, reset }: RouteErrorProps) {
  const reference = routeErrorReference(error);
  const onRetry = retry ?? reset;
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "system-ui, sans-serif",
          padding: "16px",
        }}
      >
        <title>Something went wrong — Spectrum HRMS</title>
        <main role="alert" style={{ maxWidth: 480, textAlign: "center" }}>
          <h1 style={{ fontSize: 20, margin: "0 0 8px" }}>Something went wrong</h1>
          <p style={{ margin: "0 0 16px", lineHeight: 1.5 }}>
            The application could not be displayed. Try again, or reload the page.
          </p>
          {reference ? (
            <p style={{ margin: "0 0 16px", fontSize: 14 }}>
              Reference: <code>{reference}</code>
            </p>
          ) : null}
          {onRetry ? (
            <button type="button" onClick={onRetry} style={{ padding: "8px 16px", fontSize: 14 }}>
              Try again
            </button>
          ) : null}
        </main>
      </body>
    </html>
  );
}
