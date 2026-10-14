import type { LegalEntity } from "@/lib/legal-entity/types";

export interface LegalEntityFormValues {
  name: string;
  registeredAddress: string;
  pan: string;
  tan: string;
  cin: string;
  gstin: string;
  pfCode: string;
  esiCode: string;
  lwfReg: string;
  signatoryName: string;
  signatoryDesignation: string;
  signatureImageUrl: string;
}

export type LegalEntityFormErrors = Partial<Record<keyof LegalEntityFormValues, string>>;

// Mirrors apps/api/src/hrms/modules/organisation/schemas.py `_PAN_PATTERN` / `_GSTIN_PATTERN`.
const PAN_PATTERN = /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/;
const GSTIN_PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;

export const EMPTY_LEGAL_ENTITY_FORM_VALUES: LegalEntityFormValues = {
  name: "",
  registeredAddress: "",
  pan: "",
  tan: "",
  cin: "",
  gstin: "",
  pfCode: "",
  esiCode: "",
  lwfReg: "",
  signatoryName: "",
  signatoryDesignation: "",
  signatureImageUrl: "",
};

export function legalEntityToFormValues(entity: LegalEntity): LegalEntityFormValues {
  return {
    name: entity.name,
    registeredAddress: entity.registered_address ?? "",
    pan: entity.pan ?? "",
    tan: entity.tan ?? "",
    cin: entity.cin ?? "",
    gstin: entity.gstin ?? "",
    pfCode: entity.pf_code ?? "",
    esiCode: entity.esi_code ?? "",
    lwfReg: entity.lwf_reg ?? "",
    signatoryName: entity.signatory_name ?? "",
    signatoryDesignation: entity.signatory_designation ?? "",
    signatureImageUrl: entity.signature_image_url ?? "",
  };
}

/** Full payload for `POST /legal-entities` — every field the form collects. */
export function buildCreatePayload(values: LegalEntityFormValues): Record<string, unknown> {
  return {
    name: values.name.trim(),
    registered_address: values.registeredAddress.trim() || null,
    pan: values.pan.trim() || null,
    tan: values.tan.trim() || null,
    cin: values.cin.trim() || null,
    gstin: values.gstin.trim() || null,
    pf_code: values.pfCode.trim() || null,
    esi_code: values.esiCode.trim() || null,
    lwf_reg: values.lwfReg.trim() || null,
    signatory_name: values.signatoryName.trim() || null,
    signatory_designation: values.signatoryDesignation.trim() || null,
    signature_image_url: values.signatureImageUrl.trim() || null,
  };
}

/** Diff-only payload for `PATCH /legal-entities/{id}` — mirrors `buildProfilePatch` for Company. */
export function buildUpdatePatch(
  values: LegalEntityFormValues,
  entity: LegalEntity,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};

  if (values.name.trim() !== entity.name) patch.name = values.name.trim();

  const fieldMap: Array<[keyof LegalEntityFormValues, keyof LegalEntity, string]> = [
    ["registeredAddress", "registered_address", "registered_address"],
    ["pan", "pan", "pan"],
    ["tan", "tan", "tan"],
    ["cin", "cin", "cin"],
    ["gstin", "gstin", "gstin"],
    ["pfCode", "pf_code", "pf_code"],
    ["esiCode", "esi_code", "esi_code"],
    ["lwfReg", "lwf_reg", "lwf_reg"],
    ["signatoryName", "signatory_name", "signatory_name"],
    ["signatoryDesignation", "signatory_designation", "signatory_designation"],
    ["signatureImageUrl", "signature_image_url", "signature_image_url"],
  ];

  for (const [formKey, entityKey, apiKey] of fieldMap) {
    const current = (entity[entityKey] as string | null) ?? "";
    const next = values[formKey].trim();
    if (next !== current) {
      patch[apiKey] = next || null;
    }
  }

  return patch;
}

export function validateLegalEntityForm(values: LegalEntityFormValues): LegalEntityFormErrors {
  const errors: LegalEntityFormErrors = {};

  if (!values.name.trim()) {
    errors.name = "Company name is required.";
  }

  if (values.pan.trim() && !PAN_PATTERN.test(values.pan.trim().toUpperCase())) {
    errors.pan = "Enter a valid PAN (e.g. ABCDE1234F).";
  }

  if (values.gstin.trim() && !GSTIN_PATTERN.test(values.gstin.trim().toUpperCase())) {
    errors.gstin = "Enter a valid 15-character GSTIN.";
  }

  return errors;
}
