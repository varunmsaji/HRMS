import { describe, expect, it } from "vitest";

import type { Branch } from "@/lib/branch/types";
import {
  EMPTY_BRANCH_FORM_VALUES,
  branchToFormValues,
  buildCreatePayload,
  buildUpdatePatch,
  validateBranchForm,
} from "@/lib/branch/validate-branch";

const branch: Branch = {
  id: "branch-1",
  company_id: "company-1",
  legal_entity_id: "le-1",
  name: "HQ Branch",
  code: null,
  address_line1: null,
  address_line2: null,
  city: null,
  state_code: null,
  pincode: null,
  timezone: null,
  latitude: null,
  longitude: null,
  geofence_radius_m: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("validateBranchForm", () => {
  it("requires a company", () => {
    const errors = validateBranchForm({ ...EMPTY_BRANCH_FORM_VALUES, name: "HQ" });
    expect(errors.legalEntityId).toBeDefined();
  });

  it("requires a name", () => {
    const errors = validateBranchForm({ ...EMPTY_BRANCH_FORM_VALUES, legalEntityId: "le-1" });
    expect(errors.name).toBeDefined();
  });

  it("accepts a valid state code case-insensitively", () => {
    const errors = validateBranchForm({
      ...EMPTY_BRANCH_FORM_VALUES,
      legalEntityId: "le-1",
      name: "HQ",
      stateCode: "ka",
    });
    expect(errors.stateCode).toBeUndefined();
  });

  it("rejects an invalid state code", () => {
    const errors = validateBranchForm({
      ...EMPTY_BRANCH_FORM_VALUES,
      legalEntityId: "le-1",
      name: "HQ",
      stateCode: "ZZ",
    });
    expect(errors.stateCode).toBeDefined();
  });

  it("rejects an invalid pincode", () => {
    const errors = validateBranchForm({
      ...EMPTY_BRANCH_FORM_VALUES,
      legalEntityId: "le-1",
      name: "HQ",
      pincode: "12",
    });
    expect(errors.pincode).toBeDefined();
  });

  it("accepts a valid 6-digit pincode", () => {
    const errors = validateBranchForm({
      ...EMPTY_BRANCH_FORM_VALUES,
      legalEntityId: "le-1",
      name: "HQ",
      pincode: "560001",
    });
    expect(errors.pincode).toBeUndefined();
  });

  it("rejects out-of-range latitude/longitude", () => {
    const errors = validateBranchForm({
      ...EMPTY_BRANCH_FORM_VALUES,
      legalEntityId: "le-1",
      name: "HQ",
      latitude: "999",
      longitude: "-999",
    });
    expect(errors.latitude).toBeDefined();
    expect(errors.longitude).toBeDefined();
  });

  it("rejects a non-positive geofence radius", () => {
    const errors = validateBranchForm({
      ...EMPTY_BRANCH_FORM_VALUES,
      legalEntityId: "le-1",
      name: "HQ",
      geofenceRadiusM: "0",
    });
    expect(errors.geofenceRadiusM).toBeDefined();
  });

  it("allows partial geofence data (lat/long without radius)", () => {
    const errors = validateBranchForm({
      ...EMPTY_BRANCH_FORM_VALUES,
      legalEntityId: "le-1",
      name: "HQ",
      latitude: "12.9716",
      longitude: "77.5946",
    });
    expect(errors).toEqual({});
  });

  it("treats blank optional fields as valid", () => {
    const errors = validateBranchForm({ ...EMPTY_BRANCH_FORM_VALUES, legalEntityId: "le-1", name: "HQ" });
    expect(errors).toEqual({});
  });
});

describe("branchToFormValues / buildCreatePayload", () => {
  it("round-trips name/company and nulls other optional fields", () => {
    const values = branchToFormValues(branch);
    expect(values.name).toBe("HQ Branch");
    expect(values.legalEntityId).toBe("le-1");
    expect(values.city).toBe("");

    const payload = buildCreatePayload(values);
    expect(payload).toEqual({
      legal_entity_id: "le-1",
      name: "HQ Branch",
      address_line1: null,
      address_line2: null,
      city: null,
      state_code: null,
      pincode: null,
      timezone: null,
      latitude: null,
      longitude: null,
      geofence_radius_m: null,
    });
  });

  it("includes a numeric geofence_radius_m when set", () => {
    const values = { ...branchToFormValues(branch), geofenceRadiusM: "200" };
    const payload = buildCreatePayload(values);
    expect(payload.geofence_radius_m).toBe(200);
  });
});

describe("buildUpdatePatch", () => {
  it("returns an empty patch when nothing changed", () => {
    const values = branchToFormValues(branch);
    expect(buildUpdatePatch(values, branch)).toEqual({});
  });

  it("includes only changed fields", () => {
    const values = branchToFormValues(branch);
    values.city = "Bengaluru";
    const patch = buildUpdatePatch(values, branch);
    expect(patch).toEqual({ city: "Bengaluru" });
  });

  it("nulls out a field that was cleared", () => {
    const withCity: Branch = { ...branch, city: "Bengaluru" };
    const values = branchToFormValues(withCity);
    values.city = "";
    const patch = buildUpdatePatch(values, withCity);
    expect(patch).toEqual({ city: null });
  });

  it("includes a changed legal_entity_id", () => {
    const values = branchToFormValues(branch);
    values.legalEntityId = "le-2";
    const patch = buildUpdatePatch(values, branch);
    expect(patch).toEqual({ legal_entity_id: "le-2" });
  });
});
