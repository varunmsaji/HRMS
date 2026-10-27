import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { HOLIDAY_CALENDAR_KINDS } from "@/lib/holiday-calendar/types";
import type {
  HolidayCalendarFormErrors,
  HolidayCalendarFormValues,
} from "@/lib/holiday-calendar/validate-holiday-calendar";

interface HolidayCalendarFormProps {
  values: HolidayCalendarFormValues;
  errors: HolidayCalendarFormErrors;
  onChange: (values: HolidayCalendarFormValues) => void;
  idPrefix?: string;
}

export function HolidayCalendarForm({
  values,
  errors,
  onChange,
  idPrefix = "",
}: HolidayCalendarFormProps) {
  function update<K extends keyof HolidayCalendarFormValues>(
    key: K,
    value: HolidayCalendarFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField id={id("name")} label="Calendar name" required error={errors.name}>
          <Input value={values.name} onChange={(e) => update("name", e.target.value)} />
        </FormField>
        <FormField id={id("code")} label="Code" error={errors.code}>
          <Input value={values.code} onChange={(e) => update("code", e.target.value)} />
        </FormField>
        <FormField id={id("kind")} label="Kind" required error={errors.kind}>
          <NativeSelect
            value={values.kind}
            onChange={(e) => update("kind", e.target.value as HolidayCalendarFormValues["kind"])}
          >
            {HOLIDAY_CALENDAR_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </NativeSelect>
        </FormField>
        <FormField
          id={id("stateCode")}
          label="State code"
          error={errors.stateCode}
          description="Required for regional calendars (e.g. KL, MH)."
        >
          <Input
            value={values.stateCode}
            onChange={(e) => update("stateCode", e.target.value.toUpperCase())}
          />
        </FormField>
        <FormField
          id={id("validFrom")}
          label="Valid from"
          error={errors.validFrom}
          description="Inclusive. Holidays dated before this day do not apply. Leave empty for no start."
        >
          <Input
            type="date"
            value={values.validFrom}
            onChange={(e) => update("validFrom", e.target.value)}
          />
        </FormField>
        <FormField
          id={id("validTo")}
          label="Valid to"
          error={errors.validTo}
          description="Inclusive. Holidays dated after this day do not apply. Leave empty for no end."
        >
          <Input
            type="date"
            value={values.validTo}
            onChange={(e) => update("validTo", e.target.value)}
          />
        </FormField>
      </div>
    </div>
  );
}
