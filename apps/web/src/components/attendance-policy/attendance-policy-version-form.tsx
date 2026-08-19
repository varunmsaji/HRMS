import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { PolicyBandsEditor } from "@/components/attendance-policy/policy-bands-editor";
import {
  CORE_HOURS_BREACH_BEHAVIOURS,
  EARLY_CLASSIFICATIONS,
  EXCESS_BREAK_BEHAVIOURS,
  HALF_DAY_SPLITS,
  HOUR_BAND_STATUSES,
  INCOMPLETE_AT_LOCK_BEHAVIOURS,
  LATE_CLASSIFICATIONS,
  MISSING_PUNCH_BEHAVIOURS,
  MISSING_SHIFT_BEHAVIOURS,
  MULTI_PUNCH_MODES,
  PUNCH_ROUNDING_OPTIONS,
  SPLIT_SHIFT_MISSED_BLOCK_BEHAVIOURS,
  WORK_ON_LEAVE_BEHAVIOURS,
} from "@/lib/attendance-policy/types";
import type {
  AttendancePolicyVersionFormErrors,
  AttendancePolicyVersionFormValues,
} from "@/lib/attendance-policy/validate-attendance-policy";

interface AttendancePolicyVersionFormProps {
  values: AttendancePolicyVersionFormValues;
  errors: AttendancePolicyVersionFormErrors;
  onChange: (values: AttendancePolicyVersionFormValues) => void;
}

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm text-foreground">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="rounded border-border"
      />
      {label}
    </label>
  );
}

export function AttendancePolicyVersionForm({
  values,
  errors,
  onChange,
}: AttendancePolicyVersionFormProps) {
  function update<K extends keyof AttendancePolicyVersionFormValues>(
    key: K,
    value: AttendancePolicyVersionFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Effective date</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField
            id="effective-from"
            label="Effective from"
            required
            error={errors.effectiveFrom}
            description="Required to publish. Not required while still a draft."
          >
            <Input
              type="date"
              value={values.effectiveFrom}
              onChange={(e) => update("effectiveFrom", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Grace &amp; rounding</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="grace-in" label="Grace in (minutes)">
            <Input
              type="number"
              value={values.graceInMinutes}
              onChange={(e) => update("graceInMinutes", e.target.value)}
            />
          </FormField>
          <FormField id="grace-out" label="Grace out (minutes)">
            <Input
              type="number"
              value={values.graceOutMinutes}
              onChange={(e) => update("graceOutMinutes", e.target.value)}
            />
          </FormField>
          <FormField id="punch-rounding" label="Punch rounding">
            <NativeSelect
              value={values.punchRounding}
              onChange={(e) => update("punchRounding", e.target.value)}
            >
              {PUNCH_ROUNDING_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id="rounding-minutes" label="Rounding minutes">
            <Input
              type="number"
              value={values.roundingMinutes}
              onChange={(e) => update("roundingMinutes", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Missing punch &amp; missing shift</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="missing-punch" label="Missing punch behaviour">
            <NativeSelect
              value={values.missingPunchBehaviour}
              onChange={(e) => update("missingPunchBehaviour", e.target.value)}
            >
              {MISSING_PUNCH_BEHAVIOURS.map((o) => (
                <option key={o} value={o}>
                  {o.replaceAll("_", " ")}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id="missing-shift" label="Missing shift behaviour">
            <NativeSelect
              value={values.missingShiftBehaviour}
              onChange={(e) => update("missingShiftBehaviour", e.target.value)}
            >
              {MISSING_SHIFT_BEHAVIOURS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id="auto-close-after" label="Auto-close after (minutes)">
            <Input
              type="number"
              value={values.autoCloseAfterMinutes}
              onChange={(e) => update("autoCloseAfterMinutes", e.target.value)}
            />
          </FormField>
          <div className="flex items-end pb-2">
            <Checkbox
              label="Auto-close uses shift end"
              checked={values.autoCloseUsesShiftEnd}
              onChange={(v) => update("autoCloseUsesShiftEnd", v)}
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Half-day &amp; multi-punch</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="half-day-split" label="Half-day split">
            <NativeSelect
              value={values.halfDaySplit}
              onChange={(e) => update("halfDaySplit", e.target.value)}
            >
              {HALF_DAY_SPLITS.map((o) => (
                <option key={o} value={o}>
                  {o.replaceAll("_", " ")}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id="half-day-boundary" label="Half-day boundary (minutes from start)">
            <Input
              type="number"
              value={values.halfDayBoundaryMinutes}
              onChange={(e) => update("halfDayBoundaryMinutes", e.target.value)}
            />
          </FormField>
          <FormField id="multi-punch-mode" label="Multi-punch mode">
            <NativeSelect
              value={values.multiPunchMode}
              onChange={(e) => update("multiPunchMode", e.target.value)}
            >
              {MULTI_PUNCH_MODES.map((o) => (
                <option key={o} value={o}>
                  {o.replaceAll("_", " ")}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id="duplicate-punch-window" label="Duplicate punch window (seconds)">
            <Input
              type="number"
              value={values.duplicatePunchWindowSeconds}
              onChange={(e) => update("duplicatePunchWindowSeconds", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Flexible &amp; split shift evaluation</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="core-hours-breach" label="Core-hours breach behaviour">
            <NativeSelect
              value={values.coreHoursBreachBehaviour}
              onChange={(e) => update("coreHoursBreachBehaviour", e.target.value)}
            >
              {CORE_HOURS_BREACH_BEHAVIOURS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <div className="flex items-end pb-2">
            <Checkbox
              label="Early-out uses core end"
              checked={values.earlyOutUsesCoreEnd}
              onChange={(v) => update("earlyOutUsesCoreEnd", v)}
            />
          </div>
          <FormField id="split-missed-block" label="Split shift: missed block behaviour">
            <NativeSelect
              value={values.splitShiftMissedBlockBehaviour}
              onChange={(e) => update("splitShiftMissedBlockBehaviour", e.target.value)}
            >
              {SPLIT_SHIFT_MISSED_BLOCK_BEHAVIOURS.map((o) => (
                <option key={o} value={o}>
                  {o.replaceAll("_", " ")}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <div className="flex flex-col justify-end gap-2 pb-2">
            <Checkbox
              label="Each duty block is mandatory"
              checked={values.splitShiftBlockMandatory}
              onChange={(v) => update("splitShiftBlockMandatory", v)}
            />
            <Checkbox
              label="Total hours can compensate a missed block"
              checked={values.splitShiftAllowHoursCompensation}
              onChange={(v) => update("splitShiftAllowHoursCompensation", v)}
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">WFH, on-duty &amp; leave overlay</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="work-on-leave" label="Work-on-approved-leave behaviour">
            <NativeSelect
              value={values.workOnLeaveBehaviour}
              onChange={(e) => update("workOnLeaveBehaviour", e.target.value)}
            >
              {WORK_ON_LEAVE_BEHAVIOURS.map((o) => (
                <option key={o} value={o}>
                  {o.replaceAll("_", " ")}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <div className="flex flex-col justify-end gap-2 pb-2">
            <Checkbox
              label="WFH requires punch"
              checked={values.wfhRequiresPunch}
              onChange={(v) => update("wfhRequiresPunch", v)}
            />
            <Checkbox
              label="WFH uses scheduled shift hours"
              checked={values.wfhUsesShiftHours}
              onChange={(v) => update("wfhUsesShiftHours", v)}
            />
            <Checkbox
              label="On-duty requires punch"
              checked={values.onDutyRequiresPunch}
              onChange={(v) => update("onDutyRequiresPunch", v)}
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Breaks, caps &amp; lock behaviour</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="excess-break" label="Excess break behaviour">
            <NativeSelect
              value={values.excessBreakBehaviour}
              onChange={(e) => update("excessBreakBehaviour", e.target.value)}
            >
              {EXCESS_BREAK_BEHAVIOURS.map((o) => (
                <option key={o} value={o}>
                  {o.replaceAll("_", " ")}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField
            id="lates-to-half-day"
            label="Lates-to-half-day count (per month)"
            description="Leave blank to disable this escalation."
          >
            <Input
              type="number"
              value={values.latesToHalfDayCount}
              onChange={(e) => update("latesToHalfDayCount", e.target.value)}
            />
          </FormField>
          <FormField id="incomplete-at-lock" label="Still-INCOMPLETE at lock time">
            <NativeSelect
              value={values.incompleteAtLockBehaviour}
              onChange={(e) => update("incompleteAtLockBehaviour", e.target.value)}
            >
              {INCOMPLETE_AT_LOCK_BEHAVIOURS.map((o) => (
                <option key={o} value={o}>
                  {o.replaceAll("_", " ")}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <div className="flex items-end pb-2">
            <Checkbox
              label="Early departure requires approval"
              checked={values.earlyDepartureRequiresApproval}
              onChange={(v) => update("earlyDepartureRequiresApproval", v)}
            />
          </div>
        </div>
      </section>

      <section>
        {errors.hourBands ? <p className="mb-2 text-sm text-danger">{errors.hourBands}</p> : null}
        <PolicyBandsEditor
          title="Hour bands"
          description="Worked minutes -> day status. At least one band is required to publish; bands must not overlap."
          rows={values.hourBands}
          errors={errors.hourBandRows}
          statusLabel="Result status"
          statusOptions={HOUR_BAND_STATUSES}
          showCountsTowardCap={false}
          idPrefix="hour-band"
          onChange={(rows) => update("hourBands", rows)}
        />
      </section>

      <section>
        <PolicyBandsEditor
          title="Late bands"
          description="Minutes late after grace -> classification (optional)."
          rows={values.lateBands}
          errors={errors.lateBandRows}
          statusLabel="Classification"
          statusOptions={LATE_CLASSIFICATIONS}
          showCountsTowardCap
          idPrefix="late-band"
          onChange={(rows) => update("lateBands", rows)}
        />
      </section>

      <section>
        <PolicyBandsEditor
          title="Early departure bands"
          description="Minutes early after grace -> classification (optional)."
          rows={values.earlyDepartureBands}
          errors={errors.earlyDepartureBandRows}
          statusLabel="Classification"
          statusOptions={EARLY_CLASSIFICATIONS}
          showCountsTowardCap
          idPrefix="early-band"
          onChange={(rows) => update("earlyDepartureBands", rows)}
        />
      </section>
    </div>
  );
}
