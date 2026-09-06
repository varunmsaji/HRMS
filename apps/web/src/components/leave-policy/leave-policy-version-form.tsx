import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { ACCRUAL_FREQUENCIES, APPROVAL_CHAINS } from "@/lib/leave-policy/types";
import type {
  LeavePolicyVersionFormErrors,
  LeavePolicyVersionFormValues,
} from "@/lib/leave-policy/validate-leave-policy";

interface LeavePolicyVersionFormProps {
  values: LeavePolicyVersionFormValues;
  errors: LeavePolicyVersionFormErrors;
  onChange: (values: LeavePolicyVersionFormValues) => void;
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

/** The rule configuration for a leave policy — request/approval limits, accrual, sandwich rule.
 * Mirrors `AttendancePolicyVersionForm`'s shape (no band editors here, Leave has none). */
export function LeavePolicyVersionForm({ values, errors, onChange }: LeavePolicyVersionFormProps) {
  function update<K extends keyof LeavePolicyVersionFormValues>(
    key: K,
    value: LeavePolicyVersionFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="space-y-6">
      <FormField id="lpv-effective-from" label="Effective from" required error={errors.effectiveFrom}>
        <Input
          type="date"
          value={values.effectiveFrom}
          onChange={(e) => update("effectiveFrom", e.target.value)}
        />
      </FormField>

      <div>
        <h4 className="mb-2 text-sm font-medium text-foreground">Who can submit</h4>
        <div className="flex flex-col gap-2">
          <Checkbox
            label="Employee self-service"
            checked={values.allowEmployeeRequest}
            onChange={(checked) => update("allowEmployeeRequest", checked)}
          />
          <Checkbox
            label="Manager on behalf of a report"
            checked={values.allowManagerRequestOnBehalf}
            onChange={(checked) => update("allowManagerRequestOnBehalf", checked)}
          />
          <Checkbox
            label="HR on behalf of anyone"
            checked={values.allowHrRequestOnBehalf}
            onChange={(checked) => update("allowHrRequestOnBehalf", checked)}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField
          id="lpv-max-backdated"
          label="Max backdated days"
          description="Leave blank for no limit."
        >
          <Input
            type="number"
            min={0}
            value={values.maxBackdatedDays}
            onChange={(e) => update("maxBackdatedDays", e.target.value)}
          />
        </FormField>
        <FormField
          id="lpv-max-per-month"
          label="Max requests per month"
          description="Leave blank for no limit."
        >
          <Input
            type="number"
            min={0}
            value={values.maxRequestsPerMonth}
            onChange={(e) => update("maxRequestsPerMonth", e.target.value)}
          />
        </FormField>
        <FormField id="lpv-approval-chain" label="Approval chain">
          <NativeSelect
            value={values.approvalChain}
            onChange={(e) => update("approvalChain", e.target.value)}
          >
            {APPROVAL_CHAINS.map((chain) => (
              <option key={chain} value={chain}>
                {chain}
              </option>
            ))}
          </NativeSelect>
        </FormField>
      </div>

      <div className="flex flex-col gap-2">
        <Checkbox
          label="Reason required"
          checked={values.reasonRequired}
          onChange={(checked) => update("reasonRequired", checked)}
        />
        <Checkbox
          label="Attachment required"
          checked={values.attachmentRequired}
          onChange={(checked) => update("attachmentRequired", checked)}
        />
        <Checkbox
          label="Half-day applications allowed"
          checked={values.halfDayAllowed}
          onChange={(checked) => update("halfDayAllowed", checked)}
        />
        <Checkbox
          label="Sandwich rule — a weekend/holiday bracketed between two leave days also counts as leave"
          checked={values.sandwichRuleEnabled}
          onChange={(checked) => update("sandwichRuleEnabled", checked)}
        />
        <Checkbox
          label="Reserve balance on submission — a pending (not yet approved) application blocks further balance for this leave type, not just the ledger"
          checked={values.reserveBalanceOnSubmission}
          onChange={(checked) => update("reserveBalanceOnSubmission", checked)}
        />
        <Checkbox
          label="Allowed during probation — uncheck to block employees on probation from applying for this leave type"
          checked={values.allowedDuringProbation}
          onChange={(checked) => update("allowedDuringProbation", checked)}
        />
        <Checkbox
          label="Accrue during probation — uncheck to skip monthly accrual for employees on probation"
          checked={values.accrueDuringProbation}
          onChange={(checked) => update("accrueDuringProbation", checked)}
        />
      </div>

      <div>
        <h4 className="mb-2 text-sm font-medium text-foreground">Accrual</h4>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <FormField id="lpv-accrual-frequency" label="Frequency">
            <NativeSelect
              value={values.accrualFrequency}
              onChange={(e) => update("accrualFrequency", e.target.value)}
            >
              {ACCRUAL_FREQUENCIES.map((freq) => (
                <option key={freq} value={freq}>
                  {freq}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField
            id="lpv-accrual-rate"
            label="Rate per cycle"
            error={errors.accrualRatePerCycle}
            description="Days credited each cycle."
          >
            <Input
              value={values.accrualRatePerCycle}
              onChange={(e) => update("accrualRatePerCycle", e.target.value)}
              placeholder="1.50"
            />
          </FormField>
          <FormField
            id="lpv-max-carry-forward"
            label="Max carry-forward days"
            error={errors.maxCarryForwardDays}
            description="Leave blank for unlimited."
          >
            <Input
              value={values.maxCarryForwardDays}
              onChange={(e) => update("maxCarryForwardDays", e.target.value)}
              placeholder="30"
            />
          </FormField>
        </div>
        <div className="mt-3 flex flex-col gap-2">
          <Checkbox
            label="Encashment allowed"
            checked={values.encashmentAllowed}
            onChange={(checked) => update("encashmentAllowed", checked)}
          />
          <Checkbox
            label="Allow negative balance (advance leave)"
            checked={values.allowNegativeBalance}
            onChange={(checked) => update("allowNegativeBalance", checked)}
          />
        </div>
      </div>

      <div>
        <h4 className="mb-2 text-sm font-medium text-foreground">Encashment</h4>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField
            id="lpv-max-encashment-days"
            label="Max encashment days"
            description="Leave blank for no limit. Enforced when an encashment is requested."
          >
            <Input
              value={values.maxEncashmentDays}
              onChange={(e) => update("maxEncashmentDays", e.target.value)}
              placeholder="10"
            />
          </FormField>
          <FormField
            id="lpv-min-balance-after-encashment"
            label="Minimum balance after encashment"
            description="Leave blank for no minimum. Enforced when an encashment is requested."
          >
            <Input
              value={values.minBalanceAfterEncashment}
              onChange={(e) => update("minBalanceAfterEncashment", e.target.value)}
              placeholder="5"
            />
          </FormField>
          <FormField
            id="lpv-encashment-frequency"
            label="Encashment frequency"
            description="Documented only — not enforced (needs a leave-year concept not yet decided)."
          >
            <Input
              value={values.encashmentFrequency}
              onChange={(e) => update("encashmentFrequency", e.target.value)}
              placeholder="ANNUAL"
            />
          </FormField>
          <FormField
            id="lpv-encashment-calculation-basis"
            label="Calculation basis"
            description="Documented only — for Payroll to read once it exists; Leave never computes an amount."
          >
            <Input
              value={values.encashmentCalculationBasis}
              onChange={(e) => update("encashmentCalculationBasis", e.target.value)}
              placeholder="BASIC_PAY_PER_DAY"
            />
          </FormField>
        </div>
      </div>

      <div>
        <h4 className="mb-2 text-sm font-medium text-foreground">
          Maternity entitlement split (informational)
        </h4>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField
            id="lpv-pre-delivery-days"
            label="Pre-delivery days"
            description="Documented entitlement split only — never checked against an application's dates."
          >
            <Input
              value={values.preDeliveryDays}
              onChange={(e) => update("preDeliveryDays", e.target.value)}
              placeholder="42"
            />
          </FormField>
          <FormField
            id="lpv-post-delivery-days"
            label="Post-delivery days"
            description="Documented entitlement split only — never checked against an application's dates."
          >
            <Input
              value={values.postDeliveryDays}
              onChange={(e) => update("postDeliveryDays", e.target.value)}
              placeholder="84"
            />
          </FormField>
        </div>
      </div>
    </div>
  );
}
