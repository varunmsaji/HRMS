import { FormField } from "@/components/common/form-field";
import { OvertimePolicyRateRowsEditor } from "@/components/overtime-policy/overtime-policy-rate-rows-editor";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
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

interface OvertimePolicyVersionFormProps {
  values: OvertimePolicyVersionFormValues;
  errors: OvertimePolicyVersionFormErrors;
  onChange: (values: OvertimePolicyVersionFormValues) => void;
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

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Effective date &amp; eligibility</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField
            id="ot-effective-from"
            label="Effective from"
            required
            error={errors.effectiveFrom}
          >
            <Input
              type="date"
              value={values.effectiveFrom}
              onChange={(e) => update("effectiveFrom", e.target.value)}
            />
          </FormField>
          <FormField id="ot-eligibility" label="Eligibility">
            <NativeSelect
              value={values.eligibility}
              onChange={(e) => update("eligibility", e.target.value)}
            >
              {OT_ELIGIBILITY_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o.replaceAll("_", " ")}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Detection &amp; rounding</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="ot-min-minutes" label="Minimum OT minutes">
            <Input
              type="number"
              value={values.minOtMinutes}
              onChange={(e) => update("minOtMinutes", e.target.value)}
            />
          </FormField>
          <FormField id="ot-rounding-mode" label="Rounding mode">
            <NativeSelect
              value={values.roundingMode}
              onChange={(e) => update("roundingMode", e.target.value)}
            >
              {OT_ROUNDING_MODES.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id="ot-rounding-minutes" label="Rounding minutes">
            <Input
              type="number"
              value={values.roundingMinutes}
              onChange={(e) => update("roundingMinutes", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Approval &amp; caps</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="ot-approval-chain" label="Approval chain">
            <NativeSelect
              value={values.approvalChain}
              onChange={(e) => update("approvalChain", e.target.value)}
            >
              {APPROVAL_CHAINS.map((o) => (
                <option key={o} value={o}>
                  {o.replaceAll("_", " ")}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <div className="flex flex-col justify-end gap-2 pb-2">
            <Checkbox
              label="Requires pre-approval"
              checked={values.requiresPreApproval}
              onChange={(v) => update("requiresPreApproval", v)}
            />
            <Checkbox
              label="Requires post-approval"
              checked={values.requiresPostApproval}
              onChange={(v) => update("requiresPostApproval", v)}
            />
          </div>
          <FormField id="ot-daily-cap" label="Daily cap (minutes)">
            <Input
              type="number"
              value={values.dailyCapMinutes}
              onChange={(e) => update("dailyCapMinutes", e.target.value)}
            />
          </FormField>
          <FormField id="ot-weekly-cap" label="Weekly cap (minutes)">
            <Input
              type="number"
              value={values.weeklyCapMinutes}
              onChange={(e) => update("weeklyCapMinutes", e.target.value)}
            />
          </FormField>
          <FormField id="ot-monthly-cap" label="Monthly cap (minutes)">
            <Input
              type="number"
              value={values.monthlyCapMinutes}
              onChange={(e) => update("monthlyCapMinutes", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Comp-off &amp; night OT</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex items-end pb-2">
            <Checkbox
              label="Comp-off instead of pay"
              checked={values.compOffInsteadOfPay}
              onChange={(v) => update("compOffInsteadOfPay", v)}
            />
          </div>
          <FormField id="ot-comp-off-expiry" label="Comp-off expiry (days)">
            <Input
              type="number"
              value={values.compOffExpiryDays}
              onChange={(e) => update("compOffExpiryDays", e.target.value)}
            />
          </FormField>
          <FormField
            id="ot-comp-off-day-length"
            label="Comp-off day length (minutes)"
            description="Minutes of comp-off that equal one full day on the leave balance, e.g. 480 for an 8-hour day. Leave blank to skip crediting until set."
          >
            <Input
              type="number"
              value={values.compOffDayLengthMinutes}
              onChange={(e) => update("compOffDayLengthMinutes", e.target.value)}
            />
          </FormField>
          <FormField id="ot-night-mode" label="Night OT mode">
            <NativeSelect
              value={values.nightOtMode}
              onChange={(e) => update("nightOtMode", e.target.value)}
            >
              {NIGHT_OT_MODES.map((o) => (
                <option key={o} value={o}>
                  {o.replaceAll("_", " ")}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <div className="grid grid-cols-2 gap-2">
            <FormField id="ot-night-start" label="Night window start (HH:mm)" error={errors.nightWindow}>
              <Input
                placeholder="22:00"
                value={values.nightWindowStart}
                onChange={(e) => update("nightWindowStart", e.target.value)}
              />
            </FormField>
            <FormField id="ot-night-end" label="Night window end (HH:mm)">
              <Input
                placeholder="06:00"
                value={values.nightWindowEnd}
                onChange={(e) => update("nightWindowEnd", e.target.value)}
              />
            </FormField>
          </div>
        </div>
      </section>

      <section>
        {errors.rateRows ? <p className="mb-2 text-sm text-danger">{errors.rateRows}</p> : null}
        <OvertimePolicyRateRowsEditor
          rows={values.rateRows}
          onChange={(rows) => update("rateRows", rows)}
        />
      </section>
    </div>
  );
}
