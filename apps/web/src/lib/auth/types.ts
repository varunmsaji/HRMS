/** Mirrors `apps/api/src/hrms/modules/identity/schemas.py` — the actual token/session contract. */

export interface CompanySummary {
  id: string;
  name: string;
  is_primary: boolean;
}

export interface TokenResponseData {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
  company_id: string;
  companies: CompanySummary[];
}

export interface LoginRequest {
  email: string;
  password: string;
  company_id?: string;
}

export interface UserProfile {
  id: string;
  email: string | null;
  company_id: string;
  employee_id: string | null;
  permissions: string[];
  /** `TZ-07` — the resolved business timezone (execution gate §13), shipped in the session
   * bootstrap payload so screens can compute `businessToday()` and render attendance timestamps
   * without a separate round trip. Always the company's timezone, never a per-shift/branch
   * resolution — see the field's own docstring on the backend `UserProfile` schema. */
  company_timezone: string;
  /** Platform console lifecycle status. `PENDING_APPROVAL` and `SUSPENDED` companies are
   * read-only (writes answer 403 `COMPANY_PENDING_APPROVAL` / `COMPANY_SUSPENDED`). Absent on
   * older API versions — treat as active. */
  company_status?: string;
}

export interface MeResponseData {
  user: UserProfile;
}
