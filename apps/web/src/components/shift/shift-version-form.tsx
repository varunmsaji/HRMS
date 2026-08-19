import { ShiftBreaksEditor } from "@/components/shift/shift-breaks-editor";
import { ShiftDutyBlocksEditor } from "@/components/shift/shift-duty-blocks-editor";
import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { SHIFT_VERSION_TYPES } from "@/lib/shift/types";
import type { ShiftVersionFormErrors, ShiftVersionFormValues } from "@/lib/shift/validate-shift-version";
import type { WeeklyOffPattern } from "@/lib/weekly-off-pattern/types";

interface ShiftVersionFormProps {
  values: ShiftVersionFormValues;
  errors: ShiftVersionFormErrors;
  onChange: (values: ShiftVersionFormValues) => void;
  weeklyOffPatterns: WeeklyOffPattern[];
}

const SHIFT_TYPE_LABELS: Record<string, string> = {
  FIXED: "Fixed (e.g. 09:00–18:00)",
  FLEXIBLE: "Flexible (e.g. 8-hour flex window)",
  SPLIT: "Split (e.g. 09:00–13:00 + 17:00–21:00)",
};

/** Draft-only editor for a `ShiftVersion` — the actual schedule (type, timing, breaks, duty
 * blocks). Deliberately separate from `ShiftForm` (identity) so it's obvious SHIFT = SCHEDULE,
 * not an attendance-policy engine: no grace/half-day/late/absence fields live here. */
export function ShiftVersionForm({
  values,
  errors,
  onChange,
  weeklyOffPatterns,
}: ShiftVersionFormProps) {
  function update<K extends keyof ShiftVersionFormValues>(
    key: K,
    value: ShiftVersionFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Schedule type</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="shift-type" label="Type" required error={errors.shiftType}>
            <NativeSelect
              value={values.shiftType}
              onChange={(e) =>
                update("shiftType", e.target.value as ShiftVersionFormValues["shiftType"])
              }
            >
              <option value="">Select a schedule type…</option>
              {SHIFT_VERSION_TYPES.map((type) => (
                <option key={type} value={type}>
                  {SHIFT_TYPE_LABELS[type]}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id="effective-from" label="Effective from" required error={errors.effectiveFrom}>
            <Input
              type="date"
              value={values.effectiveFrom}
              onChange={(e) => update("effectiveFrom", e.target.value)}
            />
          </FormField>
          <FormField id="timezone" label="Timezone">
            <Input
              placeholder="Asia/Kolkata"
              value={values.timezone}
              onChange={(e) => update("timezone", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      {values.shiftType === "FIXED" ? (
        <section>
          <h3 className="text-sm font-medium text-foreground">Timings</h3>
          <p className="mt-1 text-xs text-foreground-muted">
            A shift that crosses midnight (end time earlier than start time) is detected
            automatically — there is nothing extra to flag.
          </p>
          <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField id="start-time" label="Start time (HH:mm)" required error={errors.startTime}>
              <Input
                placeholder="09:00"
                value={values.startTime}
                onChange={(e) => update("startTime", e.target.value)}
              />
            </FormField>
            <FormField id="end-time" label="End time (HH:mm)" required error={errors.endTime}>
              <Input
                placeholder="18:00"
                value={values.endTime}
                onChange={(e) => update("endTime", e.target.value)}
              />
            </FormField>
          </div>
        </section>
      ) : null}

      {values.shiftType === "FLEXIBLE" ? (
        <section>
          <h3 className="text-sm font-medium text-foreground">Flexible window</h3>
          <p className="mt-1 text-xs text-foreground-muted">
            The window is the earliest/latest allowed start time — not the whole working span.
            Core hours (if any) are a separate, independently-positioned block.
          </p>
          <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField
              id="window-start"
              label="Window start (HH:mm)"
              required
              error={errors.windowStart}
            >
              <Input
                placeholder="07:00"
                value={values.windowStart}
                onChange={(e) => update("windowStart", e.target.value)}
              />
            </FormField>
            <FormField id="window-end" label="Window end (HH:mm)" required error={errors.windowEnd}>
              <Input
                placeholder="10:00"
                value={values.windowEnd}
                onChange={(e) => update("windowEnd", e.target.value)}
              />
            </FormField>
            <FormField
              id="required-minutes"
              label="Required minutes"
              required
              error={errors.requiredMinutes}
            >
              <Input
                type="number"
                value={values.requiredMinutes}
                onChange={(e) => update("requiredMinutes", e.target.value)}
              />
            </FormField>
            <FormField id="core-start" label="Core hours start (HH:mm)" error={errors.coreStart}>
              <Input
                placeholder="10:00"
                value={values.coreStart}
                onChange={(e) => update("coreStart", e.target.value)}
              />
            </FormField>
            <FormField id="core-end" label="Core hours end (HH:mm)" error={errors.coreEnd}>
              <Input
                placeholder="16:00"
                value={values.coreEnd}
                onChange={(e) => update("coreEnd", e.target.value)}
              />
            </FormField>
          </div>
        </section>
      ) : null}

      {values.shiftType === "SPLIT" ? (
        <section>
          <ShiftDutyBlocksEditor
            dutyBlocks={values.dutyBlocks}
            error={errors.dutyBlocks}
            onChange={(dutyBlocks) => update("dutyBlocks", dutyBlocks)}
          />
        </section>
      ) : null}

      {values.shiftType ? (
        <section>
          <h3 className="text-sm font-medium text-foreground">Scheduled duration</h3>
          <p className="mt-1 text-xs text-foreground-muted">Informational only — not enforced.</p>
          <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <FormField id="scheduled-minutes" label="Scheduled minutes">
              <Input
                type="number"
                value={values.scheduledMinutes}
                onChange={(e) => update("scheduledMinutes", e.target.value)}
              />
            </FormField>
            <FormField id="min-scheduled-minutes" label="Min scheduled minutes">
              <Input
                type="number"
                value={values.minScheduledMinutes}
                onChange={(e) => update("minScheduledMinutes", e.target.value)}
              />
            </FormField>
            <FormField id="max-scheduled-minutes" label="Max scheduled minutes">
              <Input
                type="number"
                value={values.maxScheduledMinutes}
                onChange={(e) => update("maxScheduledMinutes", e.target.value)}
              />
            </FormField>
          </div>
        </section>
      ) : null}

      <section>
        <h3 className="text-sm font-medium text-foreground">Flags</h3>
        <div className="mt-3 flex flex-wrap gap-4">
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
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={values.operatesOnHoliday}
              onChange={(e) => update("operatesOnHoliday", e.target.checked)}
              className="rounded border-border"
            />
            Operates on holidays
          </label>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={values.operatesOnWeeklyOff}
              onChange={(e) => update("operatesOnWeeklyOff", e.target.checked)}
              className="rounded border-border"
            />
            Operates on weekly-off days
          </label>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Weekly off</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="weekly-off-pattern" label="Shift-specific weekly-off pattern">
            <NativeSelect
              value={values.weeklyOffPatternId}
              onChange={(e) => update("weeklyOffPatternId", e.target.value)}
            >
              <option value="">Use the employee's assigned calendar</option>
              {weeklyOffPatterns.map((pattern) => (
                <option key={pattern.id} value={pattern.id}>
                  {pattern.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>
      </section>

      <section>
        <ShiftBreaksEditor
          breaks={values.breaks}
          errors={errors.breakRows}
          onChange={(breaks) => update("breaks", breaks)}
        />
      </section>
    </div>
  );
}
