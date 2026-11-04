/** Mirrors `GET /v1/companies/current/setup-checklist`: what is left to set up, worked out live
 * from the company's real data (not the registration record). */
export interface SetupChecklistItem {
  code: string;
  label: string;
  description: string;
  required: boolean;
  is_complete: boolean;
  path: string;
}

export interface SetupChecklist {
  items: SetupChecklistItem[];
  required_total: number;
  required_complete: number;
  next_code: string | null;
}
