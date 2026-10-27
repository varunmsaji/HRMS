/** Client for the platform console (`/v1/platform/*`). Separate from `apiClient` on purpose:
 * platform tokens are a different identity from tenant sessions, live only in `sessionStorage`
 * (gone when the tab closes), are never refreshed (the API issues short-lived tokens), and
 * must never be sent to — or mixed with — tenant routes. */

import { ApiError, NetworkError } from "@/lib/api/errors";
import type { ErrorEnvelope, ListEnvelope, PaginationMeta } from "@/lib/api/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "hrms.platform.session";
const TIMEOUT_MS = 30_000;

export type CompanyStatus =
  | "PENDING_APPROVAL"
  | "TRIAL"
  | "ACTIVE"
  | "SUSPENDED"
  | "REJECTED"
  | "TERMINATED";

export interface CompanyListItem {
  id: string;
  name: string;
  status: CompanyStatus;
  industry_code: string | null;
  company_size: string | null;
  created_at: string;
  trial_ends_at: string | null;
  admin_email: string | null;
  admin_name: string | null;
}

export interface CompanyDetail extends CompanyListItem {
  country_code: string;
  timezone: string;
  status_reason: string | null;
  status_changed_at: string | null;
  approved_at: string | null;
  retention_until: string | null;
  admin_locked: boolean;
  subscription: {
    plan_code: string;
    plan_name: string;
    status: string;
    trial_ends_at: string | null;
    seat_limit_override: number | null;
  } | null;
  usage: { employees: number; active_users: number };
}

export interface EmailLogItem {
  id: string;
  created_at: string;
  kind: string | null;
  provider: string;
  status: "ACCEPTED" | "FAILED" | "LOGGED_ONLY";
  recipient: string;
  sender: string | null;
  subject: string;
  company_id: string | null;
  request_id: string | null;
  failure_class: string | null;
  error_type: string | null;
  status_code: number | null;
  retryable: boolean | null;
  duration_ms: number | null;
}

export interface EmailLogDetail extends EmailLogItem {
  text_body: string | null;
  html_body: string | null;
}

export interface AuditEntry {
  id: string;
  created_at: string;
  actor_username: string | null;
  action: string;
  company_id: string | null;
  reason: string | null;
  before_status: string | null;
  after_status: string | null;
  request_id: string | null;
}

export interface Dashboard {
  counts_by_status: Record<string, number>;
  total_companies: number;
  pending_count: number;
  oldest_pending_since: string | null;
  trials_expiring_within_7_days: number;
  registrations_last_30_days: { day: string; count: number }[];
  registrations_total_30_days: number;
  locked_company_admins: number;
  active_platform_admins: number;
  pending: CompanyListItem[];
  trials_expiring: CompanyListItem[];
  retention_due: CompanyListItem[];
  recent_activity: AuditEntry[];
}

export interface PlanItem {
  code: string;
  name: string;
  description: string | null;
}

export interface PlatformAdminItem {
  id: string;
  username: string;
  status: "ACTIVE" | "DISABLED";
  locked: boolean;
  last_login_at: string | null;
  created_at: string;
  is_you: boolean;
}

interface StoredSession {
  accessToken: string;
  username: string;
  expiresAt: string;
}

export function loadPlatformSession(): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(TOKEN_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredSession;
    if (new Date(parsed.expiresAt).getTime() <= Date.now()) {
      sessionStorage.removeItem(TOKEN_KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function clearPlatformSession(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

async function call<T>(
  method: string,
  path: string,
  options: { body?: unknown; query?: Record<string, string | number | undefined>; auth?: boolean } = {},
): Promise<{ data: T; raw: unknown }> {
  const session = options.auth === false ? null : loadPlatformSession();
  if (options.auth !== false && !session) {
    throw new ApiError({ status: 401, code: "UNAUTHORIZED", message: "Please sign in again." });
  }
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(options.query ?? {})) if (v !== undefined && v !== "") search.set(k, String(v));
  const url = `${API_BASE_URL}/v1/platform${path}${search.size ? `?${search}` : ""}`;
  const requestId = crypto.randomUUID();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-Request-Id": requestId,
        ...(session ? { Authorization: `Bearer ${session.accessToken}` } : {}),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new NetworkError({ requestId });
  } finally {
    clearTimeout(timer);
  }

  if (response.status === 204) return { data: undefined as T, raw: null };
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    /* no JSON body (proxy error) */
  }
  if (!response.ok) {
    const envelope = payload as ErrorEnvelope | null;
    if (response.status === 401 && session) clearPlatformSession();
    throw new ApiError({
      status: response.status,
      code: envelope?.error?.code ?? "UNKNOWN_ERROR",
      message: envelope?.error?.message ?? "Something went wrong. Please try again.",
      details: envelope?.error?.details ?? [],
      requestId: envelope?.error?.request_id ?? response.headers.get("X-Request-Id") ?? requestId,
    });
  }
  return { data: (payload as { data: T }).data, raw: payload };
}

export const platformApi = {
  async login(username: string, password: string): Promise<void> {
    const { data } = await call<{ access_token: string; expires_at: string; username: string }>(
      "POST",
      "/auth/login",
      { body: { username, password }, auth: false },
    );
    sessionStorage.setItem(
      TOKEN_KEY,
      JSON.stringify({ accessToken: data.access_token, username: data.username, expiresAt: data.expires_at }),
    );
  },
  async logout(): Promise<void> {
    try {
      await call("POST", "/auth/logout");
    } finally {
      clearPlatformSession();
    }
  },
  dashboard: async () => (await call<Dashboard>("GET", "/dashboard")).data,
  async listCompanies(query: { status?: string; q?: string; page?: number }) {
    const { raw } = await call<CompanyListItem[]>("GET", "/companies", {
      query: { ...query, per_page: 25 },
    });
    const env = raw as ListEnvelope<CompanyListItem>;
    return { items: env.data, pagination: env.pagination as PaginationMeta };
  },
  getCompany: async (id: string) => (await call<CompanyDetail>("GET", `/companies/${id}`)).data,
  act: async (id: string, action: string, body: Record<string, unknown>) =>
    (await call<CompanyDetail>("POST", `/companies/${id}/${action}`, { body })).data,
  patchSubscription: async (id: string, body: Record<string, unknown>) =>
    (await call<CompanyDetail>("PATCH", `/companies/${id}/subscription`, { body })).data,
  unlockAdmin: async (id: string) =>
    (await call<CompanyDetail>("POST", `/companies/${id}/admin/unlock`)).data,
  plans: async () => (await call<PlanItem[]>("GET", "/plans")).data,
  resendVerification: async (id: string) =>
    (await call<CompanyDetail>("POST", `/companies/${id}/admin/resend-verification`)).data,
  listAdmins: async () => (await call<PlatformAdminItem[]>("GET", "/admins")).data,
  createAdmin: async (username: string, password: string) =>
    (await call<PlatformAdminItem>("POST", "/admins", { body: { username, password } })).data,
  setAdminStatus: async (id: string, enabled: boolean) =>
    (await call<PlatformAdminItem>("POST", `/admins/${id}/${enabled ? "enable" : "disable"}`)).data,
  resetAdminPassword: async (id: string, password: string) =>
    (await call<PlatformAdminItem>("POST", `/admins/${id}/reset-password`, { body: { password } })).data,
  async auditLog(query: { company_id?: string; action?: string; page?: number }) {
    const { raw } = await call<AuditEntry[]>("GET", "/audit-log", { query: { ...query, per_page: 25 } });
    const env = raw as ListEnvelope<AuditEntry>;
    return { items: env.data, pagination: env.pagination as PaginationMeta };
  },
  async emails(query: { status?: string; q?: string; company_id?: string; page?: number }) {
    const { raw } = await call<EmailLogItem[]>("GET", "/emails", { query: { ...query, per_page: 25 } });
    const env = raw as ListEnvelope<EmailLogItem>;
    return { items: env.data, pagination: env.pagination as PaginationMeta };
  },
  email: async (id: string) => (await call<EmailLogDetail>("GET", `/emails/${id}`)).data,
  logFiles: async () =>
    (await call<LogFiles>("GET", "/logs/files")).data,
  logEntries: async (query: {
    channel: string;
    level?: string;
    q?: string;
    request_id?: string;
    before?: string;
    limit?: number;
  }) => (await call<LogEntries>("GET", "/logs/entries", { query })).data,
};

export interface LogFileInfo {
  channel: string;
  size_bytes: number;
  modified_at: string | null;
  backups: number;
}
export interface LogFiles {
  enabled: boolean;
  files: LogFileInfo[];
}
export type LogEntry = Record<string, unknown> & {
  timestamp?: string;
  level?: string;
  event?: string;
  request_id?: string;
};
export interface LogEntries {
  channel: string;
  entries: LogEntry[];
  next_before: string | null;
  truncated: boolean;
}
