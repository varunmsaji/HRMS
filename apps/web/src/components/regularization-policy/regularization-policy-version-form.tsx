import { AdvancedSettings } from "@/components/policy/advanced-settings";
import { FormField } from "@/components/common/form-field";
import { PolicyCheckbox } from "@/components/policy/policy-checkbox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { APPROVAL_CHAIN_LABELS } from "@/lib/policy/approval-labels";
import { REGULARIZATION_TYPE_LABELS } from "@/lib/regularization-policy/labels";
import { APPROVAL_CHAINS, REGULARIZATION_TYPES } from "@/lib/regularization-policy/types";
import type {
  RegularizationPolicyVersionFormErrors,
  RegularizationPolicyVersionFormValues,
} from "@/lib/regularization-policy/validate-regularization-policy";
import { EMPTY_REGULARIZATION_POLICY_VERSION_FORM_VALUES } from "@/lib/regularization-policy/validate-regularization-policy";

interface RegularizationPolicyVersionFormProps {
  values: RegularizationPolicyVersionFormValues;
  errors: RegularizationPolicyVersionFormErrors;
  onChange: (values: RegularizationPolicyVersionFormValues) => void;
}

/** Who can ask, what can be corrected and who approves come first; the lock setting sits under
 * Advanced. The effective date is asked for when publishing.
 *
 * PD-1 — "auto-approve within" is not applied yet, so it is not shown; its stored value still
 * round-trips through the form state. */
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

  const allSelected = values.allowedTypes.length === REGULARIZATION_TYPES.length;

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Who can ask for a correction</h3>
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-3">
          <PolicyCheckbox
            label="Employees, for themselves"
            checked={values.allowEmployeeRequest}
            onChange={(v) => update("allowEmployeeRequest", v)}
          />
          <PolicyCheckbox
            label="Managers, for their team"
            checked={values.allowManagerRequest}
            onChange={(v) => update("allowManagerRequest", v)}
          />
          <PolicyCheckbox
            label="HR, for anyone"
            checked={values.allowHrRequest}
            onChange={(v) => update("allowHrRequest", v)}
          />
        </div>
      </section>

      <section>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-foreground">What can be corrected</h3>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => update("allowedTypes", allSelected ? [] : [...REGULARIZATION_TYPES])}
          >
            {allSelected ? "Clear all" : "Select all"}
          </Button>
        </div>
        <p className="mt-1 text-sm text-foreground-muted">
          Only the kinds you tick can be requested under this policy.
        </p>
        {errors.allowedTypes ? <p className="mt-1 text-sm text-danger">{errors.allowedTypes}</p> : null}
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {REGULARIZATION_TYPES.map((type) => (
            <PolicyCheckbox
              key={type}
              label={REGULARIZATION_TYPE_LABELS[type] ?? type}
              checked={values.allowedTypes.includes(type)}
              onChange={() => toggleType(type)}
            />
          ))}
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Approval and evidence</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="reg-approval-chain" label="Who approves corrections">
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
          <div className="flex flex-col justify-end gap-3 pb-2">
            <PolicyCheckbox
              label="The requester must give a reason"
              checked={values.reasonRequired}
              onChange={(v) => update("reasonRequired", v)}
            />
            <PolicyCheckbox
              label="The requester must attach proof"
              checked={values.attachmentRequired}
              onChange={(v) => update("attachmentRequired", v)}
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Limits</h3>
        <p className="mt-1 text-sm text-foreground-muted">Leave blank for no limit.</p>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField
            id="reg-max-backdated"
            label="How many days back a correction can reach"
          >
            <Input
              type="number"
              min={0}
              value={values.maxBackdatedDays}
              onChange={(e) => update("maxBackdatedDays", e.target.value)}
            />
          </FormField>
          <FormField id="reg-max-per-month" label="Requests per person per month">
            <Input
              type="number"
              min={1}
              value={values.maxRequestsPerMonth}
              onChange={(e) => update("maxRequestsPerMonth", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <AdvancedSettings
        values={values}
        defaults={EMPTY_REGULARIZATION_POLICY_VERSION_FORM_VALUES}
        fields={[
          "blockedWhenLocked",
        ]}
      >
        <div className="border-t border-border p-4">
          <PolicyCheckbox
            label="Refuse corrections for days that have been locked"
            description="On by default. Days in a closed attendance period can never be corrected, whatever this says."
            checked={values.blockedWhenLocked}
            onChange={(v) => update("blockedWhenLocked", v)}
          />
        </div>
      </AdvancedSettings>
    </div>
  );
}
