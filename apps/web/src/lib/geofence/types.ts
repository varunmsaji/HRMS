export interface GeofenceWorkplace {
  branch_id: string;
  name: string;
  code: string | null;
  is_active: boolean;
  latitude: number | null;
  longitude: number | null;
  radius_m: number | null;
  configured: boolean;
  assigned_employee_count: number;
  authorized_employee_count: number;
}

export interface WorkplaceAuthorization {
  id: string;
  employee_id: string;
  branch_id: string;
  created_by_user_id: string | null;
  created_at: string;
}

export interface GeofenceAttempt {
  id: string;
  employee_id: string;
  punch_id: string | null;
  direction: string;
  source: string;
  mode: string;
  outcome: string;
  accepted: boolean;
  branch_id: string | null;
  distance_m: string | null;
  radius_m: string | null;
  accuracy_m: string | null;
  latitude: string | null;
  longitude: string | null;
  captured_at: string | null;
  client_error: string | null;
  created_at: string;
}

/** Plain-language reading of an attempt outcome for HR reviewers. */
export const OUTCOME_LABELS: Record<string, string> = {
  INSIDE: "Inside the workplace",
  OUTSIDE_GEOFENCE: "Outside the workplace",
  OUTSIDE_GEOFENCE_UNCERTAIN: "Just outside, GPS too imprecise to be sure",
  LOCATION_TOO_INACCURATE: "GPS accuracy too poor",
  LOCATION_STALE: "Location reading too old",
  LOCATION_INVALID: "Location reading invalid",
  LOCATION_REQUIRED: "No location sent",
  LOCATION_UNAVAILABLE_CLIENT: "Phone could not provide a location",
  NO_APPLICABLE_WORKPLACE: "No approved workplace configured",
  NOT_PROVIDED: "No location sent (optional mode)",
};

export function outcomeLabel(outcome: string): string {
  return OUTCOME_LABELS[outcome] ?? outcome;
}

/** A geofence is only usable when it has coordinates and a radius. */
export function isUsableGeofence(workplace: GeofenceWorkplace): boolean {
  return workplace.is_active && workplace.configured;
}

/** External map link (no mapping library or paid provider is bundled). */
export function mapLink(latitude: number, longitude: number): string {
  return `https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=18/${latitude}/${longitude}`;
}

export function formatMetres(value: string | number | null): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${Math.round(n)} m` : "—";
}
