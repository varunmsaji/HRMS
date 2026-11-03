/** Mirrors `apps/api/src/hrms/modules/organisation/schemas.py::BranchRead`. */
export interface Branch {
  id: string;
  company_id: string;
  legal_entity_id: string;
  name: string;
  code: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state_code: string | null;
  pincode: string | null;
  timezone: string | null;
  latitude: string | null;
  longitude: string | null;
  geofence_radius_m: number | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors `BranchCreate` / `BranchUpdate` — both share the same editable field set. */
export interface BranchWritableFields {
  legal_entity_id?: string;
  name?: string;
  address_line1?: string | null;
  address_line2?: string | null;
  city?: string | null;
  state_code?: string | null;
  pincode?: string | null;
  timezone?: string | null;
  latitude?: string | null;
  longitude?: string | null;
  geofence_radius_m?: number | null;
}
