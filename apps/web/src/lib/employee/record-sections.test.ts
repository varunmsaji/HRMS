import { describe, expect, it } from "vitest";

import {
  DEPENDENTS_SECTION,
  EDUCATION_SECTION,
  EXPERIENCE_SECTION,
  IDENTITY_FORM,
  buildChangedPayload,
  buildCreatePayload,
  emptyValues,
  formatRecordValue,
  validateRecord,
  valuesFromRow,
} from "@/lib/employee/record-sections";

describe("employee record sections", () => {
  it("use the API's permissions and paths", () => {
    expect([EXPERIENCE_SECTION, EDUCATION_SECTION, DEPENDENTS_SECTION].map((s) => [s.path, s.viewPermission])).toEqual([
      ["/experience", "EMPLOYEE.VIEW_EXPERIENCE"],
      ["/education", "EMPLOYEE.VIEW_EXPERIENCE"],
      ["/dependents", "EMPLOYEE.VIEW_NOMINEE"],
    ]);
  });

  it("requires what the API requires", () => {
    expect(validateRecord(EXPERIENCE_SECTION.form, emptyValues(EXPERIENCE_SECTION.form))).toEqual({
      company_name: "Company name is required.",
      from_date: "From is required.",
    });
    expect(Object.keys(validateRecord(DEPENDENTS_SECTION.form, emptyValues(DEPENDENTS_SECTION.form)))).toEqual([
      "full_name",
      "relationship",
    ]);
  });

  it("checks PAN, Aadhaar, year and share formats", () => {
    const identity = { ...emptyValues(IDENTITY_FORM), pan_number: "abcde1234f", aadhaar_number: "12345" };
    expect(validateRecord(IDENTITY_FORM, identity)).toEqual({ aadhaar_number: "Aadhaar must be 12 digits." });
    expect(validateRecord(IDENTITY_FORM, { ...identity, pan_number: "ABC", aadhaar_number: "" })).toEqual({
      pan_number: "Enter a valid PAN, e.g. ABCDE1234F.",
    });
    expect(validateRecord(EDUCATION_SECTION.form, { qualification: "BSc", institution_name: "", year_of_passing: "1890" })).toEqual({
      year_of_passing: "Enter a year between 1950 and 2100.",
    });
    const dep = { ...emptyValues(DEPENDENTS_SECTION.form), full_name: "Asha", relationship: "Spouse", is_pf_nominee: true, pf_nominee_share_percentage: "120" };
    expect(validateRecord(DEPENDENTS_SECTION.form, dep)).toEqual({ pf_nominee_share_percentage: "Enter a share above 0 and up to 100." });
  });

  it("builds a create body: blanks omitted, money in minor units, hidden fields dropped", () => {
    const body = buildCreatePayload(EXPERIENCE_SECTION.form, {
      ...emptyValues(EXPERIENCE_SECTION.form),
      company_name: " Acme ",
      from_date: "2020-01-01",
      last_ctc_minor: "1200000.50",
    });
    expect(body).toEqual({ company_name: "Acme", from_date: "2020-01-01", last_ctc_minor: 120000050, had_prior_pf_membership: false });

    const dep = buildCreatePayload(DEPENDENTS_SECTION.form, {
      ...emptyValues(DEPENDENTS_SECTION.form),
      full_name: "Ravi",
      relationship: "Son",
      guardian_name: "typed then hidden",
      is_pf_nominee: true,
      pf_nominee_share_percentage: "50",
    });
    expect(dep).not.toHaveProperty("guardian_name");
    expect(dep.pf_nominee_share_percentage).toBe(50);
    expect(dep.is_minor).toBe(false);
  });

  it("an identity edit sends only what changed, and a cleared field as null", () => {
    const row = { pan_number: "ABCDE1234F", aadhaar_number: "123456789012", uan_number: null, father_or_husband_name: "Raj", version: 4 };
    const values = valuesFromRow(IDENTITY_FORM, row);
    expect(buildChangedPayload(IDENTITY_FORM, values, row)).toEqual({});
    expect(buildChangedPayload(IDENTITY_FORM, { ...values, uan_number: "100200300400", father_or_husband_name: "" }, row)).toEqual({
      uan_number: "100200300400",
      father_or_husband_name: null,
    });
  });

  it("formats stored values as cards show them", () => {
    expect(formatRecordValue({ key: "x", label: "x", format: "money" }, 120000050)).toBe("1200000.50");
    expect(formatRecordValue({ key: "x", label: "x", format: "yesNo" }, false)).toBe("No");
    expect(formatRecordValue({ key: "x", label: "x" }, null)).toBe("—");
    expect(valuesFromRow(EXPERIENCE_SECTION.form, { last_ctc_minor: 150000 }).last_ctc_minor).toBe("1500");
  });
});
