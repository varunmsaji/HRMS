import type { CompanySummary, TokenResponseData } from "@/lib/auth/types";

/**
 * DESIGN ASSUMPTION: the actual `POST /v1/auth/login` / `/companies/register` implementation
 * (as opposed to `docs/modules/company/04_API_Design.md`, which describes an HttpOnly refresh
 * cookie) returns `refresh_token` in the JSON body — there is no `Set-Cookie` anywhere in
 * `identity/service.py`. Without a cookie, the browser has nothing to hold the session that
 * JavaScript can't also read, so both tokens live in `localStorage` here. This keeps company_id
 * server-issued (never client-editable UI state) while acknowledging the tradeoff: an XSS bug
 * could read these tokens. Isolated to this one module so swapping to a cookie-based session
 * later (once the backend sets one) only requires changing this file and the refresh call in
 * `lib/api/client.ts`.
 */
export interface StoredSession {
  accessToken: string;
  refreshToken: string;
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
    refreshToken: data.refresh_token,
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
