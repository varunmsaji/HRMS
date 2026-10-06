import { ApiError, NetworkError } from "@/lib/api/errors";
import type { DataEnvelope, ErrorEnvelope, ListEnvelope } from "@/lib/api/types";
import {
  clearSession,
  loadSession,
  notifySessionExpired,
  saveSession,
  sessionFromTokenResponse,
} from "@/lib/auth/token-storage";
import type { TokenResponseData } from "@/lib/auth/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  /** Attach Authorization + X-Company-Id and allow the 401-refresh-retry path. Default true. */
  authenticated?: boolean;
  headers?: Record<string, string>;
  /** Optimistic-concurrency header for PATCH per docs/product/09_API_Standards.md §1.7. */
  ifMatch?: string;
  /** Return the raw envelope instead of unwrapping `.data` — list endpoints need `.pagination`
   * too (API-01). */
  rawEnvelope?: boolean;
  /** Return the response body as a file (`DownloadedFile`) instead of JSON. */
  responseType?: "json" | "file";
}

/** A file returned by `apiClient.download` — the filename comes from `Content-Disposition`. */
export interface DownloadedFile {
  blob: Blob;
  filename: string | null;
}

/** 1-indexed `page`/`per_page` query params for a paginated list endpoint (API-01). */
export interface PageQuery {
  page?: number;
  per_page?: number;
}

function withQuery(path: string, params?: Record<string, string | number | undefined>): string {
  if (!params) return path;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `${path}${path.includes("?") ? "&" : "?"}${qs}` : path;
}

function requestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `req_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

/** A fresh `Idempotency-Key` value. Keep one per user intent and resend it when retrying after a
 * network failure, so the server runs the mutation once (leave adjustments, encashments, leave
 * applications require it). Use a new one once the request has been answered. */
export function newIdempotencyKey(): string {
  return requestId();
}

async function rawRequest<T>(path: string, options: RequestOptions): Promise<T> {
  const authenticated = options.authenticated !== false;
  const session = authenticated ? loadSession() : null;

  if (authenticated && !session) {
    throw new ApiError({ status: 401, code: "UNAUTHORIZED", message: "Authentication required" });
  }

  // FormData (multipart uploads, e.g. onboarding documents) must not be JSON-stringified, and
  // the browser needs to set its own multipart boundary in Content-Type — never force
  // "application/json" on it.
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;

  const headers: Record<string, string> = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    "X-Request-Id": requestId(),
    ...options.headers,
  };
  if (options.ifMatch) headers["If-Match"] = options.ifMatch;
  if (session) {
    headers.Authorization = `Bearer ${session.accessToken}`;
    headers["X-Company-Id"] = session.companyId;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/v1${path}`, {
      method: options.method ?? "GET",
      headers,
      // SEC-06 — the API and web app are different origins even in development
      // (localhost:3000 vs localhost:8000); without `credentials: "include"` the browser
      // neither sends nor stores the HttpOnly `hrms_refresh` cookie cross-origin at all. Safe to
      // set unconditionally: the cookie is scoped server-side to `/v1/auth` (`Path` attribute),
      // so it is only ever attached to the handful of routes that actually consume it.
      credentials: "include",
      body:
        options.body === undefined
          ? undefined
          : isFormData
            ? (options.body as FormData)
            : JSON.stringify(options.body),
    });
  } catch {
    throw new NetworkError();
  }

  if (options.responseType === "file" && response.ok) {
    const disposition = response.headers.get("Content-Disposition") ?? "";
    const match = /filename="?([^";]+)"?/i.exec(disposition);
    const file: DownloadedFile = { blob: await response.blob(), filename: match?.[1] ?? null };
    return file as T;
  }

  if (response.status === 204) {
    return undefined as T;
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // No JSON body (some error paths, e.g. a proxy/502) — fall through to the generic message.
  }

  if (!response.ok) {
    const errorPayload = payload as ErrorEnvelope | null;
    throw new ApiError({
      status: response.status,
      code: errorPayload?.error?.code ?? "UNKNOWN_ERROR",
      message: errorPayload?.error?.message ?? `Request failed with status ${response.status}`,
      details: errorPayload?.error?.details ?? [],
      requestId: errorPayload?.error?.request_id ?? null,
    });
  }

  if (options.rawEnvelope) {
    return payload as T;
  }
  return (payload as DataEnvelope<T>).data;
}

let refreshInFlight: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  // SEC-06 — no token to read or send here anymore: the refresh token lives only in the
  // HttpOnly `hrms_refresh` cookie, which the browser attaches automatically because of
  // `credentials: "include"`. `loadSession()` is still checked first so a page with no prior
  // session at all doesn't fire a doomed refresh call on every 401.
  if (!loadSession()) return false;
  try {
    const res = await fetch(`${API_BASE_URL}/v1/auth/token/refresh`, {
      method: "POST",
      headers: { "X-Request-Id": requestId() },
      credentials: "include",
    });
    if (!res.ok) return false;
    const envelope = (await res.json()) as DataEnvelope<TokenResponseData>;
    saveSession(sessionFromTokenResponse(envelope.data));
    return true;
  } catch {
    return false;
  }
}

/** Ensures concurrent 401s during one page trigger a single refresh call, not one per request. */
function refreshOnce(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = refreshSession().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await rawRequest<T>(path, options);
  } catch (error) {
    const shouldAttemptRefresh =
      error instanceof ApiError &&
      error.status === 401 &&
      options.authenticated !== false &&
      loadSession() !== null;

    if (shouldAttemptRefresh) {
      const refreshed = await refreshOnce();
      if (refreshed) {
        return rawRequest<T>(path, options);
      }
      clearSession();
      notifySessionExpired();
    }
    throw error;
  }
}

export const apiClient = {
  get: <T>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...options, method: "GET" }),
  /** Paginated list endpoints (API-01) — returns the full envelope (`data` + `pagination`),
   * not just the unwrapped array, so callers can render page controls. `query` merges
   * `page`/`per_page` with any endpoint-specific filters. */
  getList: <T>(
    path: string,
    query?: PageQuery & Record<string, string | number | undefined>,
    options?: Omit<RequestOptions, "method" | "body" | "rawEnvelope">,
  ) =>
    apiRequest<ListEnvelope<T>>(withQuery(path, query), {
      ...options,
      method: "GET",
      rawEnvelope: true,
    }),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...options, method: "PATCH", body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...options, method: "PUT", body }),
  delete: <T>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...options, method: "DELETE" }),
  /** GET a file (CSV, PDF, …) with the usual auth and refresh handling. */
  download: (path: string) =>
    apiRequest<DownloadedFile>(path, { method: "GET", responseType: "file" }),
};
