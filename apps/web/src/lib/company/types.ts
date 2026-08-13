/** Mirrors `apps/api/src/hrms/modules/organisation/schemas.py::CompanyRegistrationRequest`. */
export interface CompanyRegistrationRequest {
  name: string;
  industry_code?: string;
  country_code?: string;
  currency?: string;
  timezone?: string;
  fy_start_month?: number;
  company_size?: string;
  admin_first_name: string;
  admin_last_name: string;
  admin_email: string;
  admin_password: string;
}

/** The six bands enforced server-side in `CompanyRegistrationRequest.validate_company_size`. */
export const COMPANY_SIZE_BANDS = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1000+"] as const;

/** Minimal, already-implemented lookup (`GET /v1/auth/companies/{id}`) — not the full profile. */
export interface CompanyDetail {
  id: string;
  name: string;
  status: string;
}

/**
 * Mirrors `GET/PATCH /v1/companies/current` (C-09).
 */
export interface CompanyProfile {
  id: string;
  name: string;
  legal_name: string | null;
  registration_number: string | null;
  subdomain: string | null;
  contact: { email: string | null; phone: string | null; website: string | null } | null;
  address: {
    line1: string | null;
    line2: string | null;
    city: string | null;
    state: string | null;
    postal_code: string | null;
    country_code: string | null;
  } | null;
  industry_code: string | null;
  company_size: string | null;
  country_code: string;
  currency: string;
  timezone: string;
  locale: { language_code: string; date_format: string } | null;
  fiscal_year: { start_month: number } | null;
  working_days: Array<{ day: string; is_working: boolean; is_alternate: boolean }>;
  business_hours: { start_time: string; end_time: string } | null;
  branding: { logo_url: string | null; theme: { primary_color: string } | null } | null;
  status: string;
  primary_legal_entity: unknown | null;
  onboarded_at: string | null;
  trial_ends_at: string | null;
  version: number;
}

/** Mirrors `GET /v1/companies/current/setup-progress` (C-10). */
export interface SetupStep {
  code: string;
  label: string;
  is_complete: boolean;
}

export interface CompanySetupProgressSummary {
  status: string;
  current_step: string | null;
  steps: SetupStep[];
  started_at: string;
  completed_at: string | null;
}

/** Mirrors `GET /v1/companies/current/subscription` (C-11). */
export interface SubscriptionSummary {
  plan: { code: string; name: string };
  status: string;
  current_period_start: string | null;
  current_period_end: string | null;
  trial_ends_at: string | null;
  seat_limit: number | null;
  features: Array<{
    code: string;
    is_enabled: boolean;
    source: string;
    limit_value: number | null;
  }>;
}

/**
 * Mirrors `GET /v1/dashboards/company` (C-12).
 * `null` counts mean "the counting module doesn't exist yet," never fabricated `0`.
 */
export interface CompanyDashboardSummary {
  setup_progress: { status: string; steps_completed: number; steps_total: number };
  subscription: { plan_code: string; status: string; trial_ends_at: string | null } | null;
  branch_count: number | null;
  department_count: number | null;
  employee_count: number | null;
}
