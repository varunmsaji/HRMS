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

export class NetworkError extends ApiError {
  constructor() {
    super({
      status: 0,
      code: "NETWORK_ERROR",
      message: "Could not reach the server. Check your connection and try again.",
    });
    this.name = "NetworkError";
  }
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

/** A human-readable fallback for surfaces that just need one line of text (toasts, banners). */
export function describeApiError(error: unknown): string {
  if (isApiError(error)) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}
