import type { CompanySummary, TokenResponseData } from "@/lib/auth/types";

/**
 * SEC-06 (RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md) — the refresh token no longer
 * passes through this module, or through `localStorage`, at all: every token-issuing endpoint
 * (`/auth/login`, `/auth/token/refresh`, `/companies/register`, the invite-accept endpoint) now
 * sets it as an HttpOnly `hrms_refresh` cookie (`core/auth/refresh_cookie.py`) that this page's
 * own JavaScript — and therefore an XSS payload — cannot read at all. Only the short-lived
 * (15-minute) access token and non-sensitive session metadata are kept here; the browser handles
 * sending/receiving the refresh cookie automatically on requests made with
 * `credentials: "include"` (`lib/api/client.ts`).
 */
export interface StoredSession {
  accessToken: string;
  companyId: string;
  companies: CompanySummary[];
  /** epoch ms */
  expiresAt: number;
}

const STORAGE_KEY = "hrms.session";
export const SESSION_EXPIRED_EVENT = "hrms:session-expired";

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function sessionFromTokenResponse(data: TokenResponseData): StoredSession {
  return {
    accessToken: data.access_token,
    companyId: data.company_id,
    companies: data.companies,
    expiresAt: Date.now() + data.expires_in_minutes * 60_000,
  };
}

export function loadSession(): StoredSession | null {
  if (!isBrowser()) return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredSession;
  } catch {
    return null;
  }
}

export function saveSession(session: StoredSession): void {
  if (!isBrowser()) return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  if (!isBrowser()) return;
  window.localStorage.removeItem(STORAGE_KEY);
}

/** Lets the API client (a plain module, not a React component) tell AuthProvider the session
 * died mid-page (refresh failed) without an import cycle between the two. */
export function notifySessionExpired(): void {
  if (!isBrowser()) return;
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
}
