"use client";

import { FormField } from "@/components/common/form-field";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { isShown, type RecordFormField, type RecordFormValues } from "@/lib/employee/record-sections";

interface RecordFormFieldsProps {
  fields: RecordFormField[];
  values: RecordFormValues;
  errors: Record<string, string>;
  onChange: (values: RecordFormValues) => void;
  idPrefix: string;
}

/** The inputs for one employee-record section, driven by its field list. A field with
 * `showWhen` appears only while that toggle is on. */
export function RecordFormFields({ fields, values, errors, onChange, idPrefix }: RecordFormFieldsProps) {
  const set = (key: string, value: string | boolean) => onChange({ ...values, [key]: value });
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {fields.filter((f) => isShown(f, values)).map((f) => {
        const id = `${idPrefix}${f.key}`;
        if (f.kind === "toggle") {
          return (
            <label key={f.key} htmlFor={id} className="flex items-center gap-2 text-sm text-foreground sm:col-span-2">
              <Checkbox id={id} checked={values[f.key] === true} onChange={(e) => set(f.key, e.target.checked)} />
              {f.label}
            </label>
          );
        }
        const value = String(values[f.key] ?? "");
        let input;
        if (f.kind === "multiline") {
          input = <Textarea value={value} onChange={(e) => set(f.key, e.target.value)} />;
        } else if (f.kind === "select") {
          input = (
            <NativeSelect value={value} onChange={(e) => set(f.key, e.target.value)}>
              <option value="">Not set</option>
              {(f.options ?? []).map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </NativeSelect>
          );
        } else {
          input = (
            <Input
              type={f.kind === "date" ? "date" : "text"}
              inputMode={f.kind === "money" || f.kind === "decimal" ? "decimal" : f.kind === "integer" || f.kind === "aadhaar" ? "numeric" : undefined}
              maxLength={f.kind === "aadhaar" ? 12 : f.kind === "pan" ? 10 : f.maxLength}
              autoComplete="off"
              value={value}
              onChange={(e) => set(f.key, f.kind === "pan" ? e.target.value.toUpperCase() : e.target.value)}
            />
          );
        }
        return (
          <FormField
            key={f.key}
            id={id}
            label={f.label}
            required={f.required}
            description={f.hint}
            error={errors[f.key]}
            className={f.kind === "multiline" ? "sm:col-span-2" : undefined}
          >
            {input}
          </FormField>
        );
      })}
    </div>
  );
}
