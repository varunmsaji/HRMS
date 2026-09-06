import { ApiError, NetworkError } from "@/lib/api/errors";
import type { DataEnvelope, ErrorEnvelope } from "@/lib/api/types";
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
}

function requestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `req_${Date.now()}_${Math.random().toString(16).slice(2)}`;
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

  return (payload as DataEnvelope<T>).data;
}

let refreshInFlight: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  const session = loadSession();
  if (!session?.refreshToken) return false;
  try {
    const res = await fetch(`${API_BASE_URL}/v1/auth/token/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Request-Id": requestId() },
      body: JSON.stringify({ refresh_token: session.refreshToken }),
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
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...options, method: "PATCH", body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...options, method: "PUT", body }),
  delete: <T>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...options, method: "DELETE" }),
};
