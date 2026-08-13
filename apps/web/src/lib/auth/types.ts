/** Mirrors `apps/api/src/hrms/modules/identity/schemas.py` — the actual token/session contract. */

export interface CompanySummary {
  id: string;
  name: string;
  is_primary: boolean;
}

export interface TokenResponseData {
  access_token: string;
  refresh_token: string;
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
  permissions: string[];
}

export interface MeResponseData {
  user: UserProfile;
}
