import { isApiError } from "@/lib/api/errors";

/**
 * EH-W-02 — sends a *scrubbed* description of a browser-side failure to the API so a developer can
 * find it by the reference the user was shown. Deliberately carries no message text (it can hold
 * user input or internals): only the error's class name, the top stack locations, the route
 * template-ish path without query/hash, and the build.
 *
 * Off by default. The ingestion endpoint (`POST /v1/client-errors`) is a separate, later change;
 * until then enabling this would only produce 404s. Turn it on with
 * `NEXT_PUBLIC_CLIENT_ERROR_REPORTING=true` once the endpoint exists.
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const ENABLED = process.env.NEXT_PUBLIC_CLIENT_ERROR_REPORTING === "true";

/** At most this many reports per page load, and never the same failure twice, so a render loop
 * cannot flood the API. */
const MAX_REPORTS_PER_PAGE = 10;
const MAX_FRAMES = 3;

export interface ClientErrorReport {
  source: "web";
  kind: "render" | "unhandled_rejection" | "uncaught" | "handled";
  error_class: string;
  frames: string[];
  path: string;
  /** Request id of the failed API call, when the error came from one. */
  request_id: string | null;
  reference: string | null;
}

const seen = new Set<string>();

/** `at fn (https://host/_next/static/chunks/x.js:1:2)` → `/_next/static/chunks/x.js:1:2`. */
export function topFrames(stack: string | undefined): string[] {
  if (!stack) return [];
  const frames: string[] = [];
  for (const line of stack.split("\n")) {
    const match = /\(?(https?:\/\/[^\s)]+|\/[^\s)]+:\d+:\d+)\)?\s*$/.exec(line.trim());
    if (!match) continue;
    const location = match[1]!;
    frames.push(location.replace(/^https?:\/\/[^/]+/, ""));
    if (frames.length === MAX_FRAMES) break;
  }
  return frames;
}

export function buildReport(
  error: unknown,
  kind: ClientErrorReport["kind"],
  path = typeof window !== "undefined" ? window.location.pathname : "",
): ClientErrorReport {
  const api = isApiError(error) ? error : null;
  const err = error instanceof Error ? error : null;
  return {
    source: "web",
    kind,
    error_class: api ? `ApiError:${api.status}:${api.code}` : (err?.name ?? typeof error),
    frames: topFrames(err?.stack),
    path,
    request_id: api?.requestId ?? null,
    reference: api?.reference ?? null,
  };
}

/** A user-cancelled request or an expected 4xx is not a defect; everything else is worth knowing. */
export function isReportable(error: unknown): boolean {
  if (error instanceof DOMException && error.name === "AbortError") return false;
  if (isApiError(error)) return error.status === 0 ? false : error.status >= 500;
  return true;
}

export function reportClientError(error: unknown, kind: ClientErrorReport["kind"]): void {
  try {
    if (!isReportable(error)) return;
    const report = buildReport(error, kind);
    const key = `${report.kind}|${report.error_class}|${report.frames[0] ?? ""}|${report.path}`;
    if (seen.has(key) || seen.size >= MAX_REPORTS_PER_PAGE) return;
    seen.add(key);
    if (!ENABLED) return;
    void fetch(`${API_BASE_URL}/v1/client-errors`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(report),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    // Reporting must never throw into the page it is trying to describe.
  }
}

/** Test hook: forget what was already reported. */
export function resetReportedErrors(): void {
  seen.clear();
}
