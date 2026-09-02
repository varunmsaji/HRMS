import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  PAYMENT_MODE_LABELS,
  PAYMENT_MODE_VALUES,
  type BankInfoFormValues,
  type PaymentMode,
} from "@/lib/onboarding/public-wizard";

interface BankInfoStepProps {
  values: BankInfoFormValues;
  errors: Partial<Record<keyof BankInfoFormValues, string>>;
  onChange: (values: BankInfoFormValues) => void;
}

export function BankInfoStep({ values, errors, onChange }: BankInfoStepProps) {
  function update<K extends keyof BankInfoFormValues>(key: K, value: BankInfoFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <FormField id="paymentMode" label="Payment mode" required error={errors.paymentMode}>
        <NativeSelect
          value={values.paymentMode}
          onChange={(e) => update("paymentMode", e.target.value as PaymentMode | "")}
        >
          <option value="">Select a payment mode</option>
          {PAYMENT_MODE_VALUES.map((mode) => (
            <option key={mode} value={mode}>
              {PAYMENT_MODE_LABELS[mode]}
            </option>
          ))}
        </NativeSelect>
      </FormField>
      <FormField id="accountHolderName" label="Account holder name" error={errors.accountHolderName}>
        <Input
          value={values.accountHolderName}
          onChange={(e) => update("accountHolderName", e.target.value)}
        />
      </FormField>
      <FormField
        id="accountNumber"
        label="Account number"
        error={errors.accountNumber}
        description="Only shared with HR for verification."
      >
        <Input
          type="password"
          autoComplete="off"
          value={values.accountNumber}
          onChange={(e) => update("accountNumber", e.target.value)}
        />
      </FormField>
      <FormField id="bankName" label="Bank name" error={errors.bankName}>
        <Input value={values.bankName} onChange={(e) => update("bankName", e.target.value)} />
      </FormField>
      <FormField id="ifsc" label="IFSC" error={errors.ifsc}>
        <Input
          value={values.ifsc}
          maxLength={15}
          onChange={(e) => update("ifsc", e.target.value.toUpperCase())}
        />
      </FormField>
      <FormField id="branchName" label="Branch name" error={errors.branchName}>
        <Input value={values.branchName} onChange={(e) => update("branchName", e.target.value)} />
      </FormField>
    </div>
  );
}
