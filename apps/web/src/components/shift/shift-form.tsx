import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import type { ShiftFormErrors, ShiftFormValues } from "@/lib/shift/validate-shift";

interface ShiftFormProps {
  values: ShiftFormValues;
  errors: ShiftFormErrors;
  onChange: (values: ShiftFormValues) => void;
  idPrefix?: string;
}

export function ShiftForm({ values, errors, onChange, idPrefix = "" }: ShiftFormProps) {
  function update<K extends keyof ShiftFormValues>(key: K, value: ShiftFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Identity</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("name")} label="Shift name" required error={errors.name}>
            <Input value={values.name} onChange={(e) => update("name", e.target.value)} />
          </FormField>
          <FormField id={id("code")} label="Shift code" error={errors.code}>
            <Input value={values.code} onChange={(e) => update("code", e.target.value)} />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Timings</h3>
        <p className="mt-1 text-xs text-foreground-muted">
          A shift that crosses midnight has an end time earlier than its start time — mark it
          below rather than leaving it as a validation error.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("startTime")} label="Start time (HH:mm)" required error={errors.startTime}>
            <Input
              placeholder="09:00"
              value={values.startTime}
              onChange={(e) => update("startTime", e.target.value)}
            />
          </FormField>
          <FormField id={id("endTime")} label="End time (HH:mm)" required error={errors.endTime}>
            <Input
              placeholder="18:00"
              value={values.endTime}
              onChange={(e) => update("endTime", e.target.value)}
            />
          </FormField>
        </div>
        <div className="mt-3 flex flex-wrap gap-4">
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={values.isCrossMidnight}
              onChange={(e) => update("isCrossMidnight", e.target.checked)}
              className="rounded border-border"
            />
            Crosses midnight
          </label>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={values.isNightShift}
              onChange={(e) => update("isNightShift", e.target.checked)}
              className="rounded border-border"
            />
            Night shift
          </label>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={values.isOtEligible}
              onChange={(e) => update("isOtEligible", e.target.checked)}
              className="rounded border-border"
            />
            Overtime eligible
          </label>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Breaks &amp; grace</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("breakMinutesPaid")} label="Paid break (minutes)" error={errors.breakMinutesPaid}>
            <Input
              type="number"
              value={values.breakMinutesPaid}
              onChange={(e) => update("breakMinutesPaid", e.target.value)}
            />
          </FormField>
          <FormField
            id={id("breakMinutesUnpaid")}
            label="Unpaid break (minutes)"
            error={errors.breakMinutesUnpaid}
          >
            <Input
              type="number"
              value={values.breakMinutesUnpaid}
              onChange={(e) => update("breakMinutesUnpaid", e.target.value)}
            />
          </FormField>
          <FormField id={id("graceInMinutes")} label="Grace in (minutes)" error={errors.graceInMinutes}>
            <Input
              type="number"
              value={values.graceInMinutes}
              onChange={(e) => update("graceInMinutes", e.target.value)}
            />
          </FormField>
          <FormField id={id("graceOutMinutes")} label="Grace out (minutes)" error={errors.graceOutMinutes}>
            <Input
              type="number"
              value={values.graceOutMinutes}
              onChange={(e) => update("graceOutMinutes", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Full-day / half-day hours</h3>
        <p className="mt-1 text-xs text-foreground-muted">
          Optional. Used to determine whether attendance for this shift counts as a half day or
          full day.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField
            id={id("halfDayThresholdHours")}
            label="Half-day threshold (hours)"
            error={errors.halfDayThresholdHours}
          >
            <Input
              type="number"
              step="0.5"
              value={values.halfDayThresholdHours}
              onChange={(e) => update("halfDayThresholdHours", e.target.value)}
            />
          </FormField>
          <FormField
            id={id("minHoursFullDay")}
            label="Min hours for full day"
            error={errors.minHoursFullDay}
          >
            <Input
              type="number"
              step="0.5"
              value={values.minHoursFullDay}
              onChange={(e) => update("minHoursFullDay", e.target.value)}
            />
          </FormField>
        </div>
      </section>
    </div>
  );
}
