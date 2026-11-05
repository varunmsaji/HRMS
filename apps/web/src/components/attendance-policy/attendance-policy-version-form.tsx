import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { PolicyBandsEditor } from "@/components/attendance-policy/policy-bands-editor";
import { PolicyCheckbox } from "@/components/policy/policy-checkbox";
import {
  CORE_HOURS_LABELS,
  INCOMPLETE_AT_LOCK_LABELS,
  labelOf,
  MISSING_PUNCH_LABELS,
  MISSING_SHIFT_LABELS,
  MULTI_PUNCH_LABELS,
  SPLIT_MISSED_BLOCK_LABELS,
} from "@/lib/attendance-policy/labels";
import {
  CORE_HOURS_BREACH_BEHAVIOURS,
  EARLY_CLASSIFICATIONS,
  GEOFENCE_MODES,
  GEOFENCE_MODE_LABELS,
  HOUR_BAND_STATUSES,
  INCOMPLETE_AT_LOCK_BEHAVIOURS,
  LATE_CLASSIFICATIONS,
  MISSING_PUNCH_BEHAVIOURS,
  MISSING_SHIFT_BEHAVIOURS,
  MULTI_PUNCH_MODES,
  SPLIT_SHIFT_MISSED_BLOCK_BEHAVIOURS,
} from "@/lib/attendance-policy/types";
import {
  EMPTY_ATTENDANCE_POLICY_VERSION_FORM_VALUES as DEFAULTS,
  type AttendancePolicyVersionFormErrors,
  type AttendancePolicyVersionFormValues,
} from "@/lib/attendance-policy/validate-attendance-policy";

interface AttendancePolicyVersionFormProps {
  values: AttendancePolicyVersionFormValues;
  errors: AttendancePolicyVersionFormErrors;
  onChange: (values: AttendancePolicyVersionFormValues) => void;
  /** Types of the company's live shifts. `null` when unknown, which shows every setting. */
  shiftTypesInUse?: string[] | null;
}

/** The everyday rules come first; the rest sit under Advanced, which opens by itself when one of
 * them has an error. Flexible and split-shift settings only appear when such shifts exist or the
 * stored value is not the default.
 *
 * PD-1 (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md`) — settings the engine does not apply yet
 * (punch rounding, auto-close, half-day split, excess-break behaviour, early-out-uses-core-end,
 * the split-shift block flags, the WFH flags, work-on-leave behaviour, the bands' "counts toward
 * cap" flag) are not shown; AUTO_CLOSE is only listed when a stored version already uses it. Their
 * stored values still round-trip unchanged through the form state, so saving a version never
 * resets them. The effective date is asked for when publishing. */
export function AttendancePolicyVersionForm({
  values,
  errors,
  onChange,
  shiftTypesInUse = null,
}: AttendancePolicyVersionFormProps) {
  function update<K extends keyof AttendancePolicyVersionFormValues>(
    key: K,
    value: AttendancePolicyVersionFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  const showCoreHours =
    shiftTypesInUse === null ||
    shiftTypesInUse.includes("FLEXIBLE") ||
    values.coreHoursBreachBehaviour !== DEFAULTS.coreHoursBreachBehaviour;
  const showSplit =
    shiftTypesInUse === null ||
    shiftTypesInUse.includes("SPLIT") ||
    values.splitShiftMissedBlockBehaviour !== DEFAULTS.splitShiftMissedBlockBehaviour;
  const advancedHasError = Boolean(errors.lateBandRows || errors.earlyDepartureBandRows);

  return (
    <div className="space-y-6">
      <section>
        {errors.hourBands ? <p className="mb-2 text-sm text-danger">{errors.hourBands}</p> : null}
        <PolicyBandsEditor
          title="Hours worked"
          description="Turns minutes worked into the day's result. 480 minutes is 8 hours. At least one band is needed to publish."
          rows={values.hourBands}
          errors={errors.hourBandRows}
          statusLabel="Day counts as"
          statusOptions={HOUR_BAND_STATUSES}
          showCountsTowardCap={false}
          idPrefix="hour-band"
          onChange={(rows) => update("hourBands", rows)}
        />
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Lateness and leaving early</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField
            id="grace-in"
            label="Late arrival grace (minutes)"
            description="Arriving within this time is not counted late."
          >
            <Input
              type="number"
              min={0}
              value={values.graceInMinutes}
              onChange={(e) => update("graceInMinutes", e.target.value)}
            />
          </FormField>
          <FormField
            id="grace-out"
            label="Early leaving grace (minutes)"
            description="Leaving within this time is not counted early."
          >
            <Input
              type="number"
              min={0}
              value={values.graceOutMinutes}
              onChange={(e) => update("graceOutMinutes", e.target.value)}
            />
          </FormField>
          <FormField
            id="lates-to-half-day"
            label="Late days before a half-day (per month)"
            description="With 3, every third late day (3rd, 6th, 9th) is a half-day. Leave blank to turn this off."
          >
            <Input
              type="number"
              min={1}
              value={values.latesToHalfDayCount}
              onChange={(e) => update("latesToHalfDayCount", e.target.value)}
            />
          </FormField>
          <div className="flex items-end pb-2">
            <PolicyCheckbox
              label="Leaving early needs approval"
              description="Without an approved request, leaving early gets the harshest early-leaving result."
              checked={values.earlyDepartureRequiresApproval}
              onChange={(v) => update("earlyDepartureRequiresApproval", v)}
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Missing punches</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="missing-punch" label="When a punch in or out is missing">
            <NativeSelect
              value={values.missingPunchBehaviour}
              onChange={(e) => update("missingPunchBehaviour", e.target.value)}
            >
              {MISSING_PUNCH_BEHAVIOURS.filter(
                (o) => o !== "AUTO_CLOSE" || values.missingPunchBehaviour === "AUTO_CLOSE",
              ).map((o) => (
                <option key={o} value={o}>
                  {labelOf(MISSING_PUNCH_LABELS, o)}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Location check</h3>
        <p className="mt-1 text-sm text-foreground-muted">
          Applies to punches from the mobile app only. A phone&apos;s location can be faked, so a
          pass is evidence, not proof. Start with Optional to see what Required would block.
        </p>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <FormField id="geofence-mode" label="Location check">
            <NativeSelect
              value={values.geofenceMode}
              onChange={(e) => update("geofenceMode", e.target.value)}
            >
              {GEOFENCE_MODES.map((o) => (
                <option key={o} value={o}>
                  {GEOFENCE_MODE_LABELS[o]}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          {values.geofenceMode !== "DISABLED" ? (
            <>
              <FormField
                id="geofence-max-accuracy"
                label="Worst acceptable GPS accuracy (metres)"
                description="Readings less precise than this are refused. 5-500."
                error={errors.geofenceMaxAccuracyM}
              >
                <Input
                  type="number"
                  value={values.geofenceMaxAccuracyM}
                  onChange={(e) => update("geofenceMaxAccuracyM", e.target.value)}
                />
              </FormField>
              <FormField
                id="geofence-max-age"
                label="Oldest acceptable reading (seconds)"
                description="Readings older than this are refused. 5-300."
                error={errors.geofenceMaxAgeSeconds}
              >
                <Input
                  type="number"
                  value={values.geofenceMaxAgeSeconds}
                  onChange={(e) => update("geofenceMaxAgeSeconds", e.target.value)}
                />
              </FormField>
            </>
          ) : null}
        </div>
      </section>

      <details
        open={advancedHasError || Boolean(errors.earlyInAllowanceMinutes) || undefined}
        className="rounded-md border border-border"
      >
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-foreground">
          Advanced settings
        </summary>
        <div className="space-y-6 border-t border-border p-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField
              id="early-in-allowance"
              label="Earliest punch-in before shift start (minutes)"
              description="Earlier self-service punches are refused. Early time does not count as work or overtime. Leave blank for no limit."
              error={errors.earlyInAllowanceMinutes}
            >
              <Input
                type="number"
                min={0}
                value={values.earlyInAllowanceMinutes}
                onChange={(e) => update("earlyInAllowanceMinutes", e.target.value)}
              />
            </FormField>
            <FormField id="multi-punch-mode" label="When someone punches several times a day">
              <NativeSelect
                value={values.multiPunchMode}
                onChange={(e) => update("multiPunchMode", e.target.value)}
              >
                {MULTI_PUNCH_MODES.map((o) => (
                  <option key={o} value={o}>
                    {labelOf(MULTI_PUNCH_LABELS, o)}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField
              id="duplicate-punch-window"
              label="Treat repeat punches as one within (seconds)"
              description="Absorbs accidental double taps."
            >
              <Input
                type="number"
                min={0}
                value={values.duplicatePunchWindowSeconds}
                onChange={(e) => update("duplicatePunchWindowSeconds", e.target.value)}
              />
            </FormField>
            <FormField id="missing-shift" label="When no shift can be worked out and no punches exist">
              <NativeSelect
                value={values.missingShiftBehaviour}
                onChange={(e) => update("missingShiftBehaviour", e.target.value)}
              >
                {MISSING_SHIFT_BEHAVIOURS.map((o) => (
                  <option key={o} value={o}>
                    {labelOf(MISSING_SHIFT_LABELS, o)}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField
              id="excess-break-days-to-half-day"
              label="Long-break days before a half-day (per month)"
              description="With 3, every third long-break day (3rd, 6th, 9th) is a half-day. Leave blank to turn this off."
            >
              <Input
                type="number"
                min={1}
                value={values.excessBreakDaysToHalfDayCount}
                onChange={(e) => update("excessBreakDaysToHalfDayCount", e.target.value)}
              />
            </FormField>
            <FormField id="incomplete-at-lock" label="Days still incomplete when the month closes">
              <NativeSelect
                value={values.incompleteAtLockBehaviour}
                onChange={(e) => update("incompleteAtLockBehaviour", e.target.value)}
              >
                {INCOMPLETE_AT_LOCK_BEHAVIOURS.map((o) => (
                  <option key={o} value={o}>
                    {labelOf(INCOMPLETE_AT_LOCK_LABELS, o)}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            {showCoreHours ? (
              <FormField id="core-hours-breach" label="Flexible shifts: missing core hours">
                <NativeSelect
                  value={values.coreHoursBreachBehaviour}
                  onChange={(e) => update("coreHoursBreachBehaviour", e.target.value)}
                >
                  {CORE_HOURS_BREACH_BEHAVIOURS.map((o) => (
                    <option key={o} value={o}>
                      {labelOf(CORE_HOURS_LABELS, o)}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
            ) : null}
            {showSplit ? (
              <FormField id="split-missed-block" label="Split shifts: no punch in one block">
                <NativeSelect
                  value={values.splitShiftMissedBlockBehaviour}
                  onChange={(e) => update("splitShiftMissedBlockBehaviour", e.target.value)}
                >
                  {SPLIT_SHIFT_MISSED_BLOCK_BEHAVIOURS.map((o) => (
                    <option key={o} value={o}>
                      {labelOf(SPLIT_MISSED_BLOCK_LABELS, o)}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
            ) : null}
            <div className="flex items-end pb-2">
              <PolicyCheckbox
                label="On-duty days still need punches"
                description="When off, an approved on-duty day counts as fully paid without punches."
                checked={values.onDutyRequiresPunch}
                onChange={(v) => update("onDutyRequiresPunch", v)}
              />
            </div>
          </div>
          <PolicyBandsEditor
            title="Late arrival results"
            description="Turns minutes late, after grace, into a result. Optional."
            rows={values.lateBands}
            errors={errors.lateBandRows}
            statusLabel="Result"
            statusOptions={LATE_CLASSIFICATIONS}
            showCountsTowardCap={false}
            idPrefix="late-band"
            onChange={(rows) => update("lateBands", rows)}
          />
          <PolicyBandsEditor
            title="Early leaving results"
            description="Turns minutes of leaving early, after grace, into a result. Optional."
            rows={values.earlyDepartureBands}
            errors={errors.earlyDepartureBandRows}
            statusLabel="Result"
            statusOptions={EARLY_CLASSIFICATIONS}
            showCountsTowardCap={false}
            idPrefix="early-band"
            onChange={(rows) => update("earlyDepartureBands", rows)}
          />
        </div>
      </details>
    </div>
  );
}
