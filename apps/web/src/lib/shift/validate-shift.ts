import type { Shift } from "@/lib/shift/types";

/** W2 — `Shift` is identity-only (name/code/active); schedule now lives on `ShiftVersion`
 * (see `validate-shift-version.ts`). */
export interface ShiftFormValues {
  name: string;
  code: string;
}

export type ShiftFormErrors = Partial<Record<keyof ShiftFormValues, string>>;

export const EMPTY_SHIFT_FORM_VALUES: ShiftFormValues = {
  name: "",
  code: "",
};

export function shiftToFormValues(shift: Shift): ShiftFormValues {
  return {
    name: shift.name,
    code: shift.code ?? "",
  };
}

/** Full payload for `POST /shifts`. */
export function buildCreatePayload(values: ShiftFormValues): Record<string, unknown> {
  return {
    name: values.name.trim(),
    code: values.code.trim() || null,
  };
}

/** Diff-only payload for `PATCH /shifts/{id}`. */
export function buildUpdatePatch(values: ShiftFormValues, shift: Shift): Record<string, unknown> {
  const patch: Record<string, unknown> = {};

  if (values.name.trim() !== shift.name) patch.name = values.name.trim();

  const code = values.code.trim() || null;
  if (code !== shift.code) patch.code = code;

  return patch;
}

export function validateShiftForm(values: ShiftFormValues): ShiftFormErrors {
  const errors: ShiftFormErrors = {};

  if (!values.name.trim()) {
    errors.name = "Shift name is required.";
  }

  return errors;
}
