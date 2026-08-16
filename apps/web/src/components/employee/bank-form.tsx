import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { PAYMENT_MODE_VALUES, type PaymentMode } from "@/lib/employee/types";
import { PAYMENT_MODE_LABELS, type BankFormErrors, type BankFormValues } from "@/lib/employee/validate-bank";

interface BankFormProps {
  values: BankFormValues;
  errors: BankFormErrors;
  onChange: (values: BankFormValues) => void;
  idPrefix?: string;
}

export function BankForm({ values, errors, onChange, idPrefix = "" }: BankFormProps) {
  function update<K extends keyof BankFormValues>(key: K, value: BankFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField id={id("effectiveFrom")} label="Effective from" required error={errors.effectiveFrom}>
          <Input type="date" value={values.effectiveFrom} onChange={(e) => update("effectiveFrom", e.target.value)} />
        </FormField>
        <FormField id={id("paymentMode")} label="Payment mode" required error={errors.paymentMode}>
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
        <FormField id={id("accountHolderName")} label="Account holder name" error={errors.accountHolderName}>
          <Input value={values.accountHolderName} onChange={(e) => update("accountHolderName", e.target.value)} />
        </FormField>
        <FormField
          id={id("accountNumber")}
          label="Account number"
          error={errors.accountNumber}
          description="Never shown again in full after saving — only the last 4 digits are displayed."
        >
          <Input
            type="password"
            autoComplete="off"
            value={values.accountNumber}
            onChange={(e) => update("accountNumber", e.target.value)}
          />
        </FormField>
        <FormField id={id("bankName")} label="Bank name" error={errors.bankName}>
          <Input value={values.bankName} onChange={(e) => update("bankName", e.target.value)} />
        </FormField>
        <FormField id={id("ifsc")} label="IFSC" error={errors.ifsc}>
          <Input value={values.ifsc} onChange={(e) => update("ifsc", e.target.value.toUpperCase())} maxLength={15} />
        </FormField>
        <FormField id={id("branchName")} label="Bank branch name" error={errors.branchName}>
          <Input value={values.branchName} onChange={(e) => update("branchName", e.target.value)} />
        </FormField>
      </div>
    </div>
  );
}
