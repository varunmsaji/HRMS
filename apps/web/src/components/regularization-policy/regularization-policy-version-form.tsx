import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { APPROVAL_CHAINS, REGULARIZATION_TYPES } from "@/lib/regularization-policy/types";
import type {
  RegularizationPolicyVersionFormErrors,
  RegularizationPolicyVersionFormValues,
} from "@/lib/regularization-policy/validate-regularization-policy";

interface RegularizationPolicyVersionFormProps {
  values: RegularizationPolicyVersionFormValues;
  errors: RegularizationPolicyVersionFormErrors;
  onChange: (values: RegularizationPolicyVersionFormValues) => void;
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

export function RegularizationPolicyVersionForm({
  values,
  errors,
  onChange,
}: RegularizationPolicyVersionFormProps) {
  function update<K extends keyof RegularizationPolicyVersionFormValues>(
    key: K,
    value: RegularizationPolicyVersionFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  function toggleType(type: string) {
    const next = values.allowedTypes.includes(type)
      ? values.allowedTypes.filter((t) => t !== type)
      : [...values.allowedTypes, type];
    update("allowedTypes", next);
  }

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Effective date &amp; approval</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField
            id="reg-effective-from"
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
          <FormField id="reg-approval-chain" label="Approval chain">
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
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Who may request</h3>
        <div className="mt-3 flex flex-wrap gap-4">
          <Checkbox
            label="Employee"
            checked={values.allowEmployeeRequest}
            onChange={(v) => update("allowEmployeeRequest", v)}
          />
          <Checkbox
            label="Manager"
            checked={values.allowManagerRequest}
            onChange={(v) => update("allowManagerRequest", v)}
          />
          <Checkbox
            label="HR"
            checked={values.allowHrRequest}
            onChange={(v) => update("allowHrRequest", v)}
          />
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Windows &amp; caps</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="reg-max-backdated" label="Max backdated days">
            <Input
              type="number"
              value={values.maxBackdatedDays}
              onChange={(e) => update("maxBackdatedDays", e.target.value)}
            />
          </FormField>
          <FormField id="reg-max-per-month" label="Max requests per month">
            <Input
              type="number"
              value={values.maxRequestsPerMonth}
              onChange={(e) => update("maxRequestsPerMonth", e.target.value)}
            />
          </FormField>
          {/* PD-1 — "auto-approve within" is not applied yet, so it is not shown; its stored
              value still round-trips through the form state. */}
        </div>
        <div className="mt-3 flex flex-wrap gap-4">
          <Checkbox
            label="Reason required"
            checked={values.reasonRequired}
            onChange={(v) => update("reasonRequired", v)}
          />
          <Checkbox
            label="Attachment required"
            checked={values.attachmentRequired}
            onChange={(v) => update("attachmentRequired", v)}
          />
          <Checkbox
            label="Blocked when period is locked"
            checked={values.blockedWhenLocked}
            onChange={(v) => update("blockedWhenLocked", v)}
          />
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Allowed exception types</h3>
        {errors.allowedTypes ? <p className="mt-1 text-sm text-danger">{errors.allowedTypes}</p> : null}
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {REGULARIZATION_TYPES.map((type) => (
            <Checkbox
              key={type}
              label={type.replaceAll("_", " ")}
              checked={values.allowedTypes.includes(type)}
              onChange={() => toggleType(type)}
            />
          ))}
        </div>
      </section>
    </div>
  );
}
