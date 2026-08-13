import { describe, expect, it } from "vitest";

import type { LegalEntity } from "@/lib/legal-entity/types";
import {
  EMPTY_LEGAL_ENTITY_FORM_VALUES,
  buildCreatePayload,
  buildUpdatePatch,
  legalEntityToFormValues,
  validateLegalEntityForm,
} from "@/lib/legal-entity/validate-legal-entity";

const entity: LegalEntity = {
  id: "le-1",
  company_id: "company-1",
  name: "Acme Technologies Pvt Ltd",
  registered_address: null,
  pan: null,
  tan: null,
  cin: null,
  gstin: null,
  pf_code: null,
  esi_code: null,
  lwf_reg: null,
  signatory_name: null,
  signatory_designation: null,
  signature_image_url: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("validateLegalEntityForm", () => {
  it("requires a name", () => {
    const errors = validateLegalEntityForm(EMPTY_LEGAL_ENTITY_FORM_VALUES);
    expect(errors.name).toBeDefined();
  });

  it("accepts a valid PAN and GSTIN", () => {
    const errors = validateLegalEntityForm({
      ...EMPTY_LEGAL_ENTITY_FORM_VALUES,
      name: "Acme Pvt Ltd",
      pan: "ABCDE1234F",
      gstin: "29ABCDE1234F1Z5",
    });
    expect(errors.pan).toBeUndefined();
    expect(errors.gstin).toBeUndefined();
  });

  it("rejects an invalid PAN", () => {
    const errors = validateLegalEntityForm({
      ...EMPTY_LEGAL_ENTITY_FORM_VALUES,
      name: "Acme Pvt Ltd",
      pan: "not-a-pan",
    });
    expect(errors.pan).toBeDefined();
  });

  it("rejects an invalid GSTIN", () => {
    const errors = validateLegalEntityForm({
      ...EMPTY_LEGAL_ENTITY_FORM_VALUES,
      name: "Acme Pvt Ltd",
      gstin: "invalid",
    });
    expect(errors.gstin).toBeDefined();
  });

  it("treats blank optional fields as valid", () => {
    const errors = validateLegalEntityForm({
      ...EMPTY_LEGAL_ENTITY_FORM_VALUES,
      name: "Acme Pvt Ltd",
    });
    expect(errors).toEqual({});
  });
});

describe("legalEntityToFormValues / buildCreatePayload", () => {
  it("round-trips name and nulls other optional fields", () => {
    const values = legalEntityToFormValues(entity);
    expect(values.name).toBe("Acme Technologies Pvt Ltd");
    expect(values.pan).toBe("");

    const payload = buildCreatePayload(values);
    expect(payload).toEqual({
      name: "Acme Technologies Pvt Ltd",
      registered_address: null,
      pan: null,
      tan: null,
      cin: null,
      gstin: null,
      pf_code: null,
      esi_code: null,
      lwf_reg: null,
      signatory_name: null,
      signatory_designation: null,
      signature_image_url: null,
    });
  });
});

describe("buildUpdatePatch", () => {
  it("returns an empty patch when nothing changed", () => {
    const values = legalEntityToFormValues(entity);
    expect(buildUpdatePatch(values, entity)).toEqual({});
  });

  it("includes only changed fields", () => {
    const values = legalEntityToFormValues(entity);
    values.pan = "ABCDE1234F";
    const patch = buildUpdatePatch(values, entity);
    expect(patch).toEqual({ pan: "ABCDE1234F" });
  });

  it("nulls out a field that was cleared", () => {
    const withPan: LegalEntity = { ...entity, pan: "ABCDE1234F" };
    const values = legalEntityToFormValues(withPan);
    values.pan = "";
    const patch = buildUpdatePatch(values, withPan);
    expect(patch).toEqual({ pan: null });
  });
});
