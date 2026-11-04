import { FormField } from "@/components/common/form-field";
import { OvertimePolicyRateRowsEditor } from "@/components/overtime-policy/overtime-policy-rate-rows-editor";
import { PolicyCheckbox } from "@/components/policy/policy-checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  ELIGIBILITY_LABELS,
  NIGHT_MODE_LABELS,
  ROUNDING_LABELS,
} from "@/lib/overtime-policy/labels";
import {
  APPROVAL_CHAINS,
  NIGHT_OT_MODES,
  OT_ELIGIBILITY_OPTIONS,
  OT_ROUNDING_MODES,
} from "@/lib/overtime-policy/types";
import type {
  OvertimePolicyVersionFormErrors,
  OvertimePolicyVersionFormValues,
} from "@/lib/overtime-policy/validate-overtime-policy";
import { APPROVAL_CHAIN_LABELS } from "@/lib/policy/approval-labels";

interface OvertimePolicyVersionFormProps {
  values: OvertimePolicyVersionFormValues;
  errors: OvertimePolicyVersionFormErrors;
  onChange: (values: OvertimePolicyVersionFormValues) => void;
}

/** Who earns overtime, approval, limits and comp-off come first; rounding, night overtime and
 * payroll labels sit under Advanced, which opens by itself when one of them has an error. The
 * effective date is asked for when publishing.
 *
 * PD-1 — "requires pre-approval" is not applied by the engine yet, so it is not shown; its stored
 * value still round-trips through the form state. */
export function OvertimePolicyVersionForm({
  values,
  errors,
  onChange,
}: OvertimePolicyVersionFormProps) {
  function update<K extends keyof OvertimePolicyVersionFormValues>(
    key: K,
    value: OvertimePolicyVersionFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  const showCompOffDetails =
    values.compOffInsteadOfPay || values.compOffExpiryDays !== "" || values.compOffDayLengthMinutes !== "";
  const showRoundingMinutes = values.roundingMode !== "NONE" || values.roundingMinutes !== "";
  const showNightWindow =
    values.nightOtMode !== "SHIFT_FLAG" || values.nightWindowStart !== "" || values.nightWindowEnd !== "";

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Who earns overtime</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="ot-eligibility" label="Who can earn overtime">
            <NativeSelect
              value={values.eligibility}
              onChange={(e) => update("eligibility", e.target.value)}
            >
              {/* PD-1 — GRADE_VIA_ASSIGNMENT behaves like ALWAYS today (no grade check), so it
                  is only listed when a stored version already uses it. */}
              {OT_ELIGIBILITY_OPTIONS.filter(
                (o) => o !== "GRADE_VIA_ASSIGNMENT" || values.eligibility === "GRADE_VIA_ASSIGNMENT",
              ).map((o) => (
                <option key={o} value={o}>
                  {ELIGIBILITY_LABELS[o] ?? o}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField
            id="ot-min-minutes"
            label="Minimum overtime (minutes)"
            description="Extra time shorter than this earns nothing. With 30, 20 extra minutes count as none."
          >
            <Input
              type="number"
              min={0}
              value={values.minOtMinutes}
              onChange={(e) => update("minOtMinutes", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Approval</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="ot-approval-chain" label="Who approves overtime">
            <NativeSelect
              value={values.approvalChain}
              onChange={(e) => update("approvalChain", e.target.value)}
            >
              {APPROVAL_CHAINS.map((o) => (
                <option key={o} value={o}>
                  {APPROVAL_CHAIN_LABELS[o] ?? o}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <div className="flex items-end pb-2">
            {/* PD-1 — "requires pre-approval" is not applied by the engine yet, so it is not
                shown; its stored value still round-trips through the form state. */}
            <PolicyCheckbox
              label="Approve after the overtime is worked"
              description="On by default. Overtime waits for approval before it counts."
              checked={values.requiresPostApproval}
              onChange={(v) => update("requiresPostApproval", v)}
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Limits</h3>
        <p className="mt-1 text-sm text-foreground-muted">
          The most overtime counted. Anything above is ignored. Leave blank for no limit. 240
          minutes is 4 hours.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <FormField id="ot-daily-cap" label="Per day (minutes)">
            <Input
              type="number"
              min={1}
              value={values.dailyCapMinutes}
              onChange={(e) => update("dailyCapMinutes", e.target.value)}
            />
          </FormField>
          <FormField id="ot-weekly-cap" label="Per week (minutes)">
            <Input
              type="number"
              min={1}
              value={values.weeklyCapMinutes}
              onChange={(e) => update("weeklyCapMinutes", e.target.value)}
            />
          </FormField>
          <FormField id="ot-monthly-cap" label="Per month (minutes)">
            <Input
              type="number"
              min={1}
              value={values.monthlyCapMinutes}
              onChange={(e) => update("monthlyCapMinutes", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Time off instead of pay</h3>
        <div className="mt-3 space-y-4">
          <PolicyCheckbox
            label="Give comp-off days instead of paying overtime"
            description="Needs a leave type marked as the company's comp-off type."
            checked={values.compOffInsteadOfPay}
            onChange={(v) => update("compOffInsteadOfPay", v)}
          />
          {showCompOffDetails ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField
                id="ot-comp-off-expiry"
                label="Days to use a comp-off"
                description="Leave blank for the default of 60 days."
              >
                <Input
                  type="number"
                  min={1}
                  placeholder="60"
                  value={values.compOffExpiryDays}
                  onChange={(e) => update("compOffExpiryDays", e.target.value)}
                />
              </FormField>
              <FormField
                id="ot-comp-off-day-length"
                label="Minutes that make one comp-off day"
                description="For example 480 for an 8-hour day. Leave blank to use the employee's shift length that day."
              >
                <Input
                  type="number"
                  min={1}
                  value={values.compOffDayLengthMinutes}
                  onChange={(e) => update("compOffDayLengthMinutes", e.target.value)}
                />
              </FormField>
            </div>
          ) : null}
        </div>
      </section>

      <details
        open={Boolean(errors.nightWindow || errors.rateRows) || undefined}
        className="rounded-md border border-border"
      >
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-foreground">
          Advanced settings
        </summary>
        <div className="space-y-6 border-t border-border p-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField id="ot-rounding-mode" label="Round overtime">
              <NativeSelect
                value={values.roundingMode}
                onChange={(e) => update("roundingMode", e.target.value)}
              >
                {OT_ROUNDING_MODES.map((o) => (
                  <option key={o} value={o}>
                    {ROUNDING_LABELS[o] ?? o}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            {showRoundingMinutes ? (
              <FormField
                id="ot-rounding-minutes"
                label="Round to (minutes)"
                description="For example 15 rounds to a quarter of an hour."
              >
                <Input
                  type="number"
                  min={1}
                  value={values.roundingMinutes}
                  onChange={(e) => update("roundingMinutes", e.target.value)}
                />
              </FormField>
            ) : null}
            <FormField id="ot-night-mode" label="What counts as night overtime">
              <NativeSelect
                value={values.nightOtMode}
                onChange={(e) => update("nightOtMode", e.target.value)}
              >
                {NIGHT_OT_MODES.map((o) => (
                  <option key={o} value={o}>
                    {NIGHT_MODE_LABELS[o] ?? o}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            {showNightWindow ? (
              <div className="grid grid-cols-2 gap-2">
                <FormField
                  id="ot-night-start"
                  label="Night starts (HH:mm)"
                  error={errors.nightWindow}
                >
                  <Input
                    placeholder="22:00"
                    value={values.nightWindowStart}
                    onChange={(e) => update("nightWindowStart", e.target.value)}
                  />
                </FormField>
                <FormField id="ot-night-end" label="Night ends (HH:mm)">
                  <Input
                    placeholder="06:00"
                    value={values.nightWindowEnd}
                    onChange={(e) => update("nightWindowEnd", e.target.value)}
                  />
                </FormField>
              </div>
            ) : null}
          </div>
          {errors.rateRows ? <p className="text-sm text-danger">{errors.rateRows}</p> : null}
          <OvertimePolicyRateRowsEditor
            rows={values.rateRows}
            onChange={(rows) => update("rateRows", rows)}
          />
        </div>
      </details>
    </div>
  );
}
