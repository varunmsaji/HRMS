import type { Branch } from "@/lib/branch/types";

export interface BranchFormValues {
  legalEntityId: string;
  name: string;
  addressLine1: string;
  addressLine2: string;
  city: string;
  stateCode: string;
  pincode: string;
  timezone: string;
  latitude: string;
  longitude: string;
  geofenceRadiusM: string;
}

export type BranchFormErrors = Partial<Record<keyof BranchFormValues, string>>;

// Mirrors apps/api/src/hrms/modules/organisation/schemas.py `INDIA_STATE_CODES` — ISO
// 3166-2:IN state/UT codes (28 states + 8 union territories).
export const INDIA_STATE_CODES: Record<string, string> = {
  AN: "Andaman and Nicobar Islands",
  AP: "Andhra Pradesh",
  AR: "Arunachal Pradesh",
  AS: "Assam",
  BR: "Bihar",
  CH: "Chandigarh",
  CT: "Chhattisgarh",
  DN: "Dadra and Nagar Haveli and Daman and Diu",
  DL: "Delhi",
  GA: "Goa",
  GJ: "Gujarat",
  HR: "Haryana",
  HP: "Himachal Pradesh",
  JK: "Jammu and Kashmir",
  JH: "Jharkhand",
  KA: "Karnataka",
  KL: "Kerala",
  LA: "Ladakh",
  LD: "Lakshadweep",
  MP: "Madhya Pradesh",
  MH: "Maharashtra",
  MN: "Manipur",
  ML: "Meghalaya",
  MZ: "Mizoram",
  NL: "Nagaland",
  OR: "Odisha",
  PY: "Puducherry",
  PB: "Punjab",
  RJ: "Rajasthan",
  SK: "Sikkim",
  TN: "Tamil Nadu",
  TG: "Telangana",
  TR: "Tripura",
  UP: "Uttar Pradesh",
  UT: "Uttarakhand",
  WB: "West Bengal",
};

const PINCODE_PATTERN = /^[1-9][0-9]{5}$/;

export const EMPTY_BRANCH_FORM_VALUES: BranchFormValues = {
  legalEntityId: "",
  name: "",
  addressLine1: "",
  addressLine2: "",
  city: "",
  stateCode: "",
  pincode: "",
  timezone: "",
  latitude: "",
  longitude: "",
  geofenceRadiusM: "",
};

export function branchToFormValues(branch: Branch): BranchFormValues {
  return {
    legalEntityId: branch.legal_entity_id,
    name: branch.name,
    addressLine1: branch.address_line1 ?? "",
    addressLine2: branch.address_line2 ?? "",
    city: branch.city ?? "",
    stateCode: branch.state_code ?? "",
    pincode: branch.pincode ?? "",
    timezone: branch.timezone ?? "",
    latitude: branch.latitude ?? "",
    longitude: branch.longitude ?? "",
    geofenceRadiusM: branch.geofence_radius_m != null ? String(branch.geofence_radius_m) : "",
  };
}

/** Full payload for `POST /branches` — every field the form collects. */
export function buildCreatePayload(values: BranchFormValues): Record<string, unknown> {
  return {
    legal_entity_id: values.legalEntityId,
    name: values.name.trim(),
    address_line1: values.addressLine1.trim() || null,
    address_line2: values.addressLine2.trim() || null,
    city: values.city.trim() || null,
    state_code: values.stateCode.trim() || null,
    pincode: values.pincode.trim() || null,
    timezone: values.timezone.trim() || null,
    latitude: values.latitude.trim() || null,
    longitude: values.longitude.trim() || null,
    geofence_radius_m: values.geofenceRadiusM.trim() ? Number(values.geofenceRadiusM) : null,
  };
}

/** Diff-only payload for `PATCH /branches/{id}` — mirrors `buildUpdatePatch` for Company. */
export function buildUpdatePatch(values: BranchFormValues, branch: Branch): Record<string, unknown> {
  const patch: Record<string, unknown> = {};

  if (values.legalEntityId !== branch.legal_entity_id) {
    patch.legal_entity_id = values.legalEntityId;
  }
  if (values.name.trim() !== branch.name) patch.name = values.name.trim();

  const stringFieldMap: Array<[keyof BranchFormValues, keyof Branch, string]> = [
    ["addressLine1", "address_line1", "address_line1"],
    ["addressLine2", "address_line2", "address_line2"],
    ["city", "city", "city"],
    ["stateCode", "state_code", "state_code"],
    ["pincode", "pincode", "pincode"],
    ["timezone", "timezone", "timezone"],
    ["latitude", "latitude", "latitude"],
    ["longitude", "longitude", "longitude"],
  ];

  for (const [formKey, branchKey, apiKey] of stringFieldMap) {
    const current = (branch[branchKey] as string | null) ?? "";
    const next = values[formKey].trim();
    if (next !== current) {
      patch[apiKey] = next || null;
    }
  }

  const currentRadius = branch.geofence_radius_m != null ? String(branch.geofence_radius_m) : "";
  const nextRadius = values.geofenceRadiusM.trim();
  if (nextRadius !== currentRadius) {
    patch.geofence_radius_m = nextRadius ? Number(nextRadius) : null;
  }

  return patch;
}

export function validateBranchForm(values: BranchFormValues): BranchFormErrors {
  const errors: BranchFormErrors = {};

  if (!values.legalEntityId.trim()) {
    errors.legalEntityId = "Select a company.";
  }

  if (!values.name.trim()) {
    errors.name = "Branch name is required.";
  }

  if (values.stateCode.trim() && !(values.stateCode.trim().toUpperCase() in INDIA_STATE_CODES)) {
    errors.stateCode = "Select a valid state or union territory.";
  }

  if (values.pincode.trim() && !PINCODE_PATTERN.test(values.pincode.trim())) {
    errors.pincode = "Enter a valid 6-digit PIN code.";
  }

  if (values.latitude.trim()) {
    const lat = Number(values.latitude.trim());
    if (Number.isNaN(lat) || lat < -90 || lat > 90) {
      errors.latitude = "Latitude must be between -90 and 90.";
    }
  }

  if (values.longitude.trim()) {
    const lng = Number(values.longitude.trim());
    if (Number.isNaN(lng) || lng < -180 || lng > 180) {
      errors.longitude = "Longitude must be between -180 and 180.";
    }
  }

  if (values.geofenceRadiusM.trim()) {
    const radius = Number(values.geofenceRadiusM.trim());
    if (Number.isNaN(radius) || radius <= 0) {
      errors.geofenceRadiusM = "Geofence radius must be a positive number.";
    }
  }

  return errors;
}
