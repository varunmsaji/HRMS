import { AdvancedSettings } from "@/components/policy/advanced-settings";
import { FormField } from "@/components/common/form-field";
import { PolicyCheckbox } from "@/components/policy/policy-checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { ACCRUAL_LABELS, LEAVE_APPROVAL_LABELS } from "@/lib/leave-policy/labels";
import {
  ACCRUAL_FREQUENCIES,
  APPROVAL_CHAINS,
  YEAR_END_ACTION_LABELS,
  YEAR_END_ACTIONS,
} from "@/lib/leave-policy/types";
import type {
  LeavePolicyVersionFormErrors,
  LeavePolicyVersionFormValues,
} from "@/lib/leave-policy/validate-leave-policy";
import { EMPTY_LEAVE_POLICY_VERSION_FORM_VALUES } from "@/lib/leave-policy/validate-leave-policy";

interface LeavePolicyVersionFormProps {
  values: LeavePolicyVersionFormValues;
  errors: LeavePolicyVersionFormErrors;
  onChange: (values: LeavePolicyVersionFormValues) => void;
}

/** Who can apply, who approves, how days are credited and what happens at year end come first.
 * Limits, probation, negative balance, encashment and the maternity split sit under Advanced,
 * which opens by itself when one of them has an error. The effective date is asked for when
 * publishing. */
export function LeavePolicyVersionForm({ values, errors, onChange }: LeavePolicyVersionFormProps) {
  function update<K extends keyof LeavePolicyVersionFormValues>(
    key: K,
    value: LeavePolicyVersionFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  const credits = values.accrualFrequency !== "NONE";

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Applying and approval</h3>
        <div className="mt-3 flex flex-col gap-2">
          <PolicyCheckbox
            label="Employees can apply for themselves"
            checked={values.allowEmployeeRequest}
            onChange={(checked) => update("allowEmployeeRequest", checked)}
          />
          <PolicyCheckbox
            label="Managers can apply for their reports"
            checked={values.allowManagerRequestOnBehalf}
            onChange={(checked) => update("allowManagerRequestOnBehalf", checked)}
          />
          <PolicyCheckbox
            label="HR can apply for anyone"
            checked={values.allowHrRequestOnBehalf}
            onChange={(checked) => update("allowHrRequestOnBehalf", checked)}
          />
        </div>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="lpv-approval-chain" label="Who approves">
            <NativeSelect
              value={values.approvalChain}
              onChange={(e) => update("approvalChain", e.target.value)}
            >
              {APPROVAL_CHAINS.map((chain) => (
                <option key={chain} value={chain}>
                  {LEAVE_APPROVAL_LABELS[chain]}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>
        <div className="mt-3 flex flex-col gap-2">
          <PolicyCheckbox
            label="Employees must give a reason"
            checked={values.reasonRequired}
            onChange={(checked) => update("reasonRequired", checked)}
          />
          <PolicyCheckbox
            label="Half-day leave is allowed"
            checked={values.halfDayAllowed}
            onChange={(checked) => update("halfDayAllowed", checked)}
          />
          <PolicyCheckbox
            label="Count weekly offs and holidays between two leave days"
            description="If someone takes leave on both sides of a weekend or holiday, that day is counted as leave too, even when the two sides are separate applications of the same leave type."
            checked={values.sandwichRuleEnabled}
            onChange={(checked) => update("sandwichRuleEnabled", checked)}
          />
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Balance</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="lpv-accrual-frequency" label="Days are credited">
            <NativeSelect
              value={values.accrualFrequency}
              onChange={(e) => update("accrualFrequency", e.target.value)}
            >
              {ACCRUAL_FREQUENCIES.map((freq) => (
                <option key={freq} value={freq}>
                  {ACCRUAL_LABELS[freq]}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          {credits ? (
            <FormField
              id="lpv-accrual-rate"
              label="Days credited each time"
              required
              error={errors.accrualRatePerCycle}
            >
              <Input
                value={values.accrualRatePerCycle}
                onChange={(e) => update("accrualRatePerCycle", e.target.value)}
                placeholder="1.5"
              />
            </FormField>
          ) : null}
          <FormField
            id="lpv-year-end-action"
            label="At the end of the leave year"
            description="For example casual leave lapses, and earned leave carries forward up to a limit."
          >
            <NativeSelect
              value={values.yearEndAction}
              onChange={(e) => update("yearEndAction", e.target.value)}
            >
              {YEAR_END_ACTIONS.map((action) => (
                <option key={action} value={action}>
                  {YEAR_END_ACTION_LABELS[action]}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          {values.yearEndAction !== "LAPSE" ? (
            <FormField
              id="lpv-max-carry-forward"
              label="Most days that carry forward"
              required={values.yearEndAction === "ENCASH_EXCESS"}
              error={errors.maxCarryForwardDays}
              description={
                values.yearEndAction === "ENCASH_EXCESS"
                  ? "Days above this are encashed."
                  : "Leave blank to carry everything forward."
              }
            >
              <Input
                value={values.maxCarryForwardDays}
                onChange={(e) => update("maxCarryForwardDays", e.target.value)}
                placeholder="30"
              />
            </FormField>
          ) : null}
        </div>
      </section>

      <AdvancedSettings
        values={values}
        defaults={EMPTY_LEAVE_POLICY_VERSION_FORM_VALUES}
        fields={[
          "maxBackdatedDays",
          "maxRequestsPerMonth",
          "attachmentRequired",
          "reserveBalanceOnSubmission",
          "allowedDuringProbation",
          "accrueDuringProbation",
          "allowNegativeBalance",
          "negativeBalanceFloor",
          "encashmentAllowed",
          "maxEncashmentDays",
          "minBalanceAfterEncashment",
          "encashmentFrequency",
          "encashmentCalculationBasis",
          "preDeliveryDays",
          "postDeliveryDays",
        ]}
        hasError={Boolean(errors.negativeBalanceFloor)}
      >
        <div className="space-y-6 border-t border-border p-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField
              id="lpv-max-backdated"
              label="Furthest back an application can start (days)"
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
              label="Most applications per month"
              description="Leave blank for no limit."
            >
              <Input
                type="number"
                min={0}
                value={values.maxRequestsPerMonth}
                onChange={(e) => update("maxRequestsPerMonth", e.target.value)}
              />
            </FormField>
          </div>

          <div className="flex flex-col gap-2">
            <PolicyCheckbox
              label="Employees must attach a document"
              checked={values.attachmentRequired}
              onChange={(checked) => update("attachmentRequired", checked)}
            />
            <PolicyCheckbox
              label="Hold the days as soon as someone applies"
              description="Pending applications reduce the balance that can be used for other applications."
              checked={values.reserveBalanceOnSubmission}
              onChange={(checked) => update("reserveBalanceOnSubmission", checked)}
            />
            <PolicyCheckbox
              label="Employees on probation can apply"
              checked={values.allowedDuringProbation}
              onChange={(checked) => update("allowedDuringProbation", checked)}
            />
            <PolicyCheckbox
              label="Employees on probation earn days"
              checked={values.accrueDuringProbation}
              onChange={(checked) => update("accrueDuringProbation", checked)}
            />
            <PolicyCheckbox
              label="Balance can go below zero"
              checked={values.allowNegativeBalance}
              onChange={(checked) => update("allowNegativeBalance", checked)}
            />
          </div>
          {values.allowNegativeBalance ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField
                id="lpv-negative-balance-floor"
                label="Days below zero allowed"
                required
                error={errors.negativeBalanceFloor}
                description="For example 3 lets the balance go down to −3. The deficit is recovered at exit."
              >
                <Input
                  value={values.negativeBalanceFloor}
                  onChange={(e) => update("negativeBalanceFloor", e.target.value)}
                  placeholder="3"
                />
              </FormField>
            </div>
          ) : null}

          <div>
            <PolicyCheckbox
              label="Unused days can be encashed"
              checked={values.encashmentAllowed}
              onChange={(checked) => update("encashmentAllowed", checked)}
            />
            {values.encashmentAllowed ? (
              <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                <FormField
                  id="lpv-max-encashment-days"
                  label="Most days that can be encashed"
                  description="Leave blank for no limit."
                >
                  <Input
                    value={values.maxEncashmentDays}
                    onChange={(e) => update("maxEncashmentDays", e.target.value)}
                    placeholder="10"
                  />
                </FormField>
                <FormField
                  id="lpv-min-balance-after-encashment"
                  label="Balance that must stay after encashing"
                  description="Leave blank for no minimum."
                >
                  <Input
                    value={values.minBalanceAfterEncashment}
                    onChange={(e) => update("minBalanceAfterEncashment", e.target.value)}
                    placeholder="5"
                  />
                </FormField>
                <FormField
                  id="lpv-encashment-frequency"
                  label="How often (note only)"
                  description="Recorded for reference. Not enforced."
                >
                  <Input
                    value={values.encashmentFrequency}
                    onChange={(e) => update("encashmentFrequency", e.target.value)}
                    placeholder="ANNUAL"
                  />
                </FormField>
                <FormField
                  id="lpv-encashment-calculation-basis"
                  label="How it is paid (note only)"
                  description="Recorded for payroll to read. Leave never works out an amount."
                >
                  <Input
                    value={values.encashmentCalculationBasis}
                    onChange={(e) => update("encashmentCalculationBasis", e.target.value)}
                    placeholder="BASIC_PAY_PER_DAY"
                  />
                </FormField>
              </div>
            ) : null}
          </div>

          <div>
            <h4 className="text-sm font-medium text-foreground">Maternity split (note only)</h4>
            <p className="text-xs text-foreground-muted">
              Recorded for reference. Never checked against an application&apos;s dates.
            </p>
            <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField id="lpv-pre-delivery-days" label="Days before delivery">
                <Input
                  value={values.preDeliveryDays}
                  onChange={(e) => update("preDeliveryDays", e.target.value)}
                  placeholder="42"
                />
              </FormField>
              <FormField id="lpv-post-delivery-days" label="Days after delivery">
                <Input
                  value={values.postDeliveryDays}
                  onChange={(e) => update("postDeliveryDays", e.target.value)}
                  placeholder="84"
                />
              </FormField>
            </div>
          </div>
        </div>
      </AdvancedSettings>
    </div>
  );
}
