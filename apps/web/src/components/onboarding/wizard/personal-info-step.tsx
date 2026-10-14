import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  BLOOD_GROUP_VALUES,
  GENDER_LABELS,
  GENDER_VALUES,
  MARITAL_STATUS_LABELS,
  MARITAL_STATUS_VALUES,
  type PersonalInfoFormValues,
} from "@/lib/onboarding/public-wizard";

interface PersonalInfoStepProps {
  values: PersonalInfoFormValues;
  errors: Partial<Record<keyof PersonalInfoFormValues, string>>;
  onChange: (values: PersonalInfoFormValues) => void;
}

export function PersonalInfoStep({ values, errors, onChange }: PersonalInfoStepProps) {
  function update<K extends keyof PersonalInfoFormValues>(key: K, value: PersonalInfoFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <FormField id="firstName" label="First name" required error={errors.firstName}>
        <Input value={values.firstName} onChange={(e) => update("firstName", e.target.value)} />
      </FormField>
      <FormField id="middleName" label="Middle name" error={errors.middleName}>
        <Input value={values.middleName} onChange={(e) => update("middleName", e.target.value)} />
      </FormField>
      <FormField id="lastName" label="Last name" error={errors.lastName}>
        <Input value={values.lastName} onChange={(e) => update("lastName", e.target.value)} />
      </FormField>
      <FormField id="dateOfBirth" label="Date of birth" error={errors.dateOfBirth}>
        <Input type="date" value={values.dateOfBirth} onChange={(e) => update("dateOfBirth", e.target.value)} />
      </FormField>
      <FormField id="gender" label="Gender" error={errors.gender}>
        <NativeSelect value={values.gender} onChange={(e) => update("gender", e.target.value)}>
          <option value="">Select gender</option>
          {GENDER_VALUES.map((value) => (
            <option key={value} value={value}>
              {GENDER_LABELS[value]}
            </option>
          ))}
        </NativeSelect>
      </FormField>
      <FormField id="bloodGroup" label="Blood group" error={errors.bloodGroup}>
        <NativeSelect
          value={values.bloodGroup}
          onChange={(e) => update("bloodGroup", e.target.value)}
        >
          <option value="">Select blood group</option>
          {BLOOD_GROUP_VALUES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </NativeSelect>
      </FormField>
      <FormField id="maritalStatus" label="Marital status" error={errors.maritalStatus}>
        <NativeSelect
          value={values.maritalStatus}
          onChange={(e) => update("maritalStatus", e.target.value)}
        >
          <option value="">Select marital status</option>
          {MARITAL_STATUS_VALUES.map((value) => (
            <option key={value} value={value}>
              {MARITAL_STATUS_LABELS[value]}
            </option>
          ))}
        </NativeSelect>
      </FormField>
      <FormField id="nationality" label="Nationality" error={errors.nationality}>
        <Input value={values.nationality} onChange={(e) => update("nationality", e.target.value)} />
      </FormField>
      <FormField
        id="fatherOrHusbandName"
        label="Father's / husband's name"
        error={errors.fatherOrHusbandName}
      >
        <Input
          value={values.fatherOrHusbandName}
          onChange={(e) => update("fatherOrHusbandName", e.target.value)}
        />
      </FormField>
      <FormField id="panNumber" label="PAN number" error={errors.panNumber}>
        <Input
          value={values.panNumber}
          maxLength={10}
          onChange={(e) => update("panNumber", e.target.value.toUpperCase())}
          placeholder="ABCDE1234F"
        />
      </FormField>
      <FormField id="aadhaarNumber" label="Aadhaar number" error={errors.aadhaarNumber}>
        <Input
          value={values.aadhaarNumber}
          maxLength={12}
          onChange={(e) => update("aadhaarNumber", e.target.value.replace(/\D/g, ""))}
          placeholder="12-digit Aadhaar number"
        />
      </FormField>
    </div>
  );
}
