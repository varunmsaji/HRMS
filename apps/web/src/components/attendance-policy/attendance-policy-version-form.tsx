import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { PolicyBandsEditor } from "@/components/attendance-policy/policy-bands-editor";
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

/** PD-1 (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md`) — settings the engine does not apply yet
 * (punch rounding, auto-close, half-day split, excess-break behaviour, early-out-uses-core-end,
 * the split-shift block flags, the WFH flags, work-on-leave behaviour, the bands' "counts toward
 * cap" flag) are not shown; AUTO_CLOSE is only listed when a stored version already uses it. Their
 * stored values still round-trip unchanged through the form state, so saving a version never
 * resets them. */
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
        <h3 className="text-sm font-medium text-foreground">Grace</h3>
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
              {MISSING_PUNCH_BEHAVIOURS.filter(
                (o) => o !== "AUTO_CLOSE" || values.missingPunchBehaviour === "AUTO_CLOSE",
              ).map((o) => (
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
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Multi-punch</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
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
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">On-duty</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col justify-end gap-2 pb-2">
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
          <FormField
            id="excess-break-days-to-half-day"
            label="Excess-break-days-to-half-day count (per month)"
            description="Leave blank to disable this escalation."
          >
            <Input
              type="number"
              value={values.excessBreakDaysToHalfDayCount}
              onChange={(e) => update("excessBreakDaysToHalfDayCount", e.target.value)}
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
        <h3 className="mb-1 text-sm font-semibold text-foreground">Location check (geofencing)</h3>
        <p className="mb-3 text-sm text-muted-foreground">
          Applies to employee self-service punches from the mobile app only. HR corrections and
          regularizations are never location-checked. Device location can be spoofed, so a pass
          is evidence, not proof of presence. Start with Optional to see what Required would do.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
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
          showCountsTowardCap={false}
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
          showCountsTowardCap={false}
          idPrefix="early-band"
          onChange={(rows) => update("earlyDepartureBands", rows)}
        />
      </section>
    </div>
  );
}
