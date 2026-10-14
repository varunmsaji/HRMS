import type { ErrorDetail } from "@/lib/api/types";

/** Thrown for every non-2xx API response and for network failures (status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ErrorDetail[];
  readonly requestId: string | null;

  constructor(params: {
    status: number;
    code: string;
    message: string;
    details?: ErrorDetail[];
    requestId?: string | null;
  }) {
    super(params.message);
    this.name = "ApiError";
    this.status = params.status;
    this.code = params.code;
    this.details = params.details ?? [];
    this.requestId = params.requestId ?? null;
  }
}

/**
 * The request never produced an HTTP response (status 0). `code` says why:
 * - `NETWORK_ERROR` — the server could not be reached (DNS, refused, CORS-blocked);
 * - `OFFLINE` — the browser reports no connectivity at all;
 * - `REQUEST_TIMEOUT` — no response within the client's timeout. For a write the outcome is
 *   unknown: the server may have applied it, so callers must not resubmit blindly.
 * `requestId` is the id this client sent, so support can still find the attempt in server logs.
 */
export class NetworkError extends ApiError {
  constructor(params: { code?: string; message?: string; requestId?: string | null } = {}) {
    super({
      status: 0,
      code: params.code ?? "NETWORK_ERROR",
      message: params.message ?? "Could not reach the server. Check your connection and try again.",
      requestId: params.requestId ?? null,
    });
    this.name = "NetworkError";
  }
}

export function offlineError(requestId: string | null): NetworkError {
  return new NetworkError({
    code: "OFFLINE",
    message: "You appear to be offline. Check your connection and try again.",
    requestId,
  });
}

export function timeoutError(requestId: string | null, isWrite: boolean): NetworkError {
  return new NetworkError({
    code: "REQUEST_TIMEOUT",
    message: isWrite
      ? "The server took too long to respond. Your change may or may not have been saved — refresh to check before trying again."
      : "The server took too long to respond. Please try again.",
    requestId,
  });
}

/**
 * FastAPI's own `RequestValidationError` handler joins Pydantic's `loc` tuple with "." (e.g.
 * "body.admin_password"), while `AppError`s raised directly from service code use the bare
 * field name (e.g. "admin_password" — see `organisation/service.py`'s weak-password check).
 * Matching on the last dot-segment handles both without the caller needing to know which path
 * produced the error.
 */
export function getFieldError(details: ErrorDetail[], field: string): string | undefined {
  return details.find((detail) => {
    if (!detail.field) return false;
    const segments = detail.field.split(".");
    return segments[segments.length - 1] === field;
  })?.message;
}

/** Extract the current resource from a STALE_RESOURCE error, when provided by the API. */
export function getStaleResourceCurrent<T>(error: ApiError): T | null {
  const detail = error.details.find((item) => item.code === "STALE_RESOURCE");
  const context = detail?.context;
  if (!context || typeof context !== "object") return null;
  const current = (context as { current?: unknown }).current;
  return current && typeof current === "object" ? (current as T) : null;
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/**
 * The support reference for a failure the user cannot fix themselves (a server error or no
 * response at all) — the request id the API logged it under. `null` for ordinary 4xx outcomes
 * (validation, permission, conflict), which the message already explains.
 */
export function errorReference(error: unknown): string | null {
  if (!isApiError(error) || !error.requestId) return null;
  return error.status === 0 || error.status >= 500 ? error.requestId : null;
}

/** True when repeating the *same read* is reasonable: no response, a gateway/availability
 * failure, or rate limiting. Never use this to resubmit a write automatically. */
export function isRetryableError(error: unknown): boolean {
  if (!isApiError(error)) return false;
  return error.status === 0 || error.status === 429 || [502, 503, 504].includes(error.status);
}

/** A human-readable fallback for surfaces that just need one line of text (toasts, banners).
 * Server and connectivity failures carry their support reference. */
export function describeApiError(error: unknown): string {
  if (isApiError(error)) {
    const reference = errorReference(error);
    return reference ? `${error.message} (Reference: ${reference})` : error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

/**
 * Human-readable text for the employee-lifecycle rejections: an assignment pointing at an
 * inactive master record (`INACTIVE_<KIND>`, 422), deactivating a master record active employees
 * still depend on (`MASTER_DATA_HAS_ACTIVE_EMPLOYEES`, 409), a compensation in a currency other
 * than the company's (`COMPENSATION_CURRENCY_MISMATCH`, 422) and a non-positive CTC. Anything
 * else falls back to {@link describeApiError}.
 */
export function describeLifecycleError(error: unknown): string {
  if (!isApiError(error)) return describeApiError(error);
  const detail = error.details[0];
  const code = detail?.code ?? error.code;

  if (code === "MASTER_DATA_HAS_ACTIVE_EMPLOYEES") {
    const context = detail?.context as { kind?: string; active_employee_count?: number } | undefined;
    const kind = context?.kind ?? "record";
    const count = context?.active_employee_count;
    const who =
      typeof count === "number"
        ? `${count} active employee${count === 1 ? " is" : "s are"}`
        : "Active employees are";
    return `This ${kind} can't be deactivated: ${who} still assigned to it. Reassign them first, then try again.`;
  }
  if (code.startsWith("INACTIVE_")) {
    return detail?.message ?? "That selection is inactive. Choose an active one.";
  }
  if (code === "COMPENSATION_CURRENCY_MISMATCH") {
    return detail?.message
      ? `Compensation must be in the company currency — ${detail.message}.`
      : "Compensation must be in the company's currency.";
  }
  if (error.status === 422 && detail?.message) return detail.message;
  return error.message;
}
