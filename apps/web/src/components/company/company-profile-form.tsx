import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { COMPANY_SIZE_BANDS } from "@/lib/company/types";
import type {
  CompanyProfileFormErrors,
  CompanyProfileFormValues,
} from "@/lib/company/validate-company-profile";
import { listTimezones } from "@/lib/timezones";

const DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"] as const;
const DAY_LABELS: Record<(typeof DAYS)[number], string> = {
  MON: "Monday",
  TUE: "Tuesday",
  WED: "Wednesday",
  THU: "Thursday",
  FRI: "Friday",
  SAT: "Saturday",
  SUN: "Sunday",
};

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

interface CompanyProfileFormProps {
  values: CompanyProfileFormValues;
  errors: CompanyProfileFormErrors;
  onChange: (values: CompanyProfileFormValues) => void;
  currencyLocked: boolean;
}

export function CompanyProfileForm({
  values,
  errors,
  onChange,
  currencyLocked,
}: CompanyProfileFormProps) {
  const timezones = listTimezones();

  function update<K extends keyof CompanyProfileFormValues>(
    key: K,
    value: CompanyProfileFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  function toggleWorkingDay(day: string, checked: boolean) {
    onChange({
      ...values,
      workingDays: { ...values.workingDays, [day]: checked },
    });
  }

  return (
    <div className="space-y-8">
      <section>
        <h3 className="text-sm font-medium text-foreground">Basic information</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="name" label="Company name" required error={errors.name}>
            <Input value={values.name} onChange={(e) => update("name", e.target.value)} />
          </FormField>
          <FormField id="legalName" label="Legal name" error={errors.legalName}>
            <Input value={values.legalName} onChange={(e) => update("legalName", e.target.value)} />
          </FormField>
          <FormField id="registrationNumber" label="Registration number" error={errors.registrationNumber}>
            <Input
              value={values.registrationNumber}
              onChange={(e) => update("registrationNumber", e.target.value)}
            />
          </FormField>
          <FormField id="industryCode" label="Industry code" error={errors.industryCode}>
            <Input value={values.industryCode} onChange={(e) => update("industryCode", e.target.value)} />
          </FormField>
          <FormField id="companySize" label="Company size" error={errors.companySize}>
            <NativeSelect
              value={values.companySize}
              onChange={(e) => update("companySize", e.target.value)}
            >
              <option value="">Select size</option>
              {COMPANY_SIZE_BANDS.map((band) => (
                <option key={band} value={band}>
                  {band}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id="countryCode" label="Country code" error={errors.countryCode}>
            <Input value={values.countryCode} onChange={(e) => update("countryCode", e.target.value)} />
          </FormField>
          <FormField
            id="currency"
            label="Currency"
            error={errors.currency}
            description={currencyLocked ? "Currency cannot be changed after trial." : undefined}
          >
            <Input
              value={values.currency}
              onChange={(e) => update("currency", e.target.value.toUpperCase())}
              disabled={currencyLocked}
            />
          </FormField>
          <FormField id="timezone" label="Timezone" error={errors.timezone}>
            <NativeSelect
              value={values.timezone}
              onChange={(e) => update("timezone", e.target.value)}
            >
              {timezones.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Contact information</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <FormField id="contactEmail" label="Email" error={errors.contactEmail}>
            <Input
              type="email"
              value={values.contactEmail}
              onChange={(e) => update("contactEmail", e.target.value)}
            />
          </FormField>
          <FormField id="contactPhone" label="Phone" error={errors.contactPhone}>
            <Input value={values.contactPhone} onChange={(e) => update("contactPhone", e.target.value)} />
          </FormField>
          <FormField id="website" label="Website" error={errors.website}>
            <Input value={values.website} onChange={(e) => update("website", e.target.value)} />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Address</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="addressLine1" label="Line 1" error={errors.addressLine1}>
            <Input value={values.addressLine1} onChange={(e) => update("addressLine1", e.target.value)} />
          </FormField>
          <FormField id="addressLine2" label="Line 2" error={errors.addressLine2}>
            <Input value={values.addressLine2} onChange={(e) => update("addressLine2", e.target.value)} />
          </FormField>
          <FormField id="addressCity" label="City" error={errors.addressCity}>
            <Input value={values.addressCity} onChange={(e) => update("addressCity", e.target.value)} />
          </FormField>
          <FormField id="addressState" label="State" error={errors.addressState}>
            <Input value={values.addressState} onChange={(e) => update("addressState", e.target.value)} />
          </FormField>
          <FormField id="addressPostalCode" label="Postal code" error={errors.addressPostalCode}>
            <Input
              value={values.addressPostalCode}
              onChange={(e) => update("addressPostalCode", e.target.value)}
            />
          </FormField>
          <FormField id="addressCountryCode" label="Country code" error={errors.addressCountryCode}>
            <Input
              value={values.addressCountryCode}
              onChange={(e) => update("addressCountryCode", e.target.value.toUpperCase())}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Localization</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <FormField id="languageCode" label="Language code" error={errors.languageCode}>
            <Input value={values.languageCode} onChange={(e) => update("languageCode", e.target.value)} />
          </FormField>
          <FormField id="dateFormat" label="Date format" error={errors.dateFormat}>
            <Input value={values.dateFormat} onChange={(e) => update("dateFormat", e.target.value)} />
          </FormField>
          <FormField id="fiscalYearStartMonth" label="Fiscal year start" error={errors.fiscalYearStartMonth}>
            <NativeSelect
              value={values.fiscalYearStartMonth}
              onChange={(e) => update("fiscalYearStartMonth", e.target.value)}
            >
              {MONTHS.map((label, index) => (
                <option key={label} value={String(index + 1)}>
                  {label}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Working schedule</h3>
        <p className="mt-1 text-xs text-foreground-muted">Select the company&apos;s default working days.</p>
        {errors.workingDays ? (
          <p className="mt-2 text-xs text-danger" role="alert">
            {errors.workingDays}
          </p>
        ) : null}
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {DAYS.map((day) => (
            <label key={day} className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={values.workingDays[day] ?? false}
                onChange={(e) => toggleWorkingDay(day, e.target.checked)}
                className="rounded border-border"
              />
              {DAY_LABELS[day]}
            </label>
          ))}
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Business hours</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="businessHoursStart" label="Start (HH:mm)" error={errors.businessHoursStart}>
            <Input
              placeholder="09:00"
              value={values.businessHoursStart}
              onChange={(e) => update("businessHoursStart", e.target.value)}
            />
          </FormField>
          <FormField id="businessHoursEnd" label="End (HH:mm)" error={errors.businessHoursEnd}>
            <Input
              placeholder="18:00"
              value={values.businessHoursEnd}
              onChange={(e) => update("businessHoursEnd", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Branding</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="logoUrl" label="Logo URL" error={errors.logoUrl}>
            <Input value={values.logoUrl} onChange={(e) => update("logoUrl", e.target.value)} />
          </FormField>
          <FormField id="primaryColor" label="Primary color" error={errors.primaryColor}>
            <Input
              placeholder="#4F46E5"
              value={values.primaryColor}
              onChange={(e) => update("primaryColor", e.target.value)}
            />
          </FormField>
        </div>
      </section>
    </div>
  );
}
