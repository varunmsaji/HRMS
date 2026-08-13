/** Mirrors `apps/api/src/hrms/modules/organisation/schemas.py::LegalEntityRead`. */
export interface LegalEntity {
  id: string;
  company_id: string;
  name: string;
  registered_address: string | null;
  pan: string | null;
  tan: string | null;
  cin: string | null;
  gstin: string | null;
  pf_code: string | null;
  esi_code: string | null;
  lwf_reg: string | null;
  signatory_name: string | null;
  signatory_designation: string | null;
  signature_image_url: string | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Mirrors `LegalEntityCreate` / `LegalEntityUpdate` — both share the same editable field set. */
export interface LegalEntityWritableFields {
  name?: string;
  registered_address?: string | null;
  pan?: string | null;
  tan?: string | null;
  cin?: string | null;
  gstin?: string | null;
  pf_code?: string | null;
  esi_code?: string | null;
  lwf_reg?: string | null;
  signatory_name?: string | null;
  signatory_designation?: string | null;
  signature_image_url?: string | null;
}
