"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { FormField } from "@/components/common/form-field";
import { PasswordInput } from "@/components/common/password-input";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { AuthLayout } from "@/components/layout/auth-layout";
import { ApiError, getFieldError } from "@/lib/api/errors";
import { apiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import type { TokenResponseData } from "@/lib/auth/types";
import { COMPANY_SIZE_BANDS } from "@/lib/company/types";
import {
  buildRegistrationPayload,
  emptyRegistrationForm,
  validateRegistrationForm,
  type RegistrationFormErrors,
  type RegistrationFormValues,
} from "@/lib/company/validate-registration";
import { fetchAllowedCompanyTimezones } from "@/lib/timezones";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export default function RegisterPage() {
  const router = useRouter();
  const { applyTokenResponse } = useAuth();
  // `DEC-TZ-02` (SELECTED) — filtered to what the server will actually accept (execution gate
  // §6.3), fetched from the API rather than the full ~600-zone `Intl` list this page showed
  // before Phase 2. Defaults to `Asia/Kolkata` alone while the fetch is in flight or if it
  // fails, matching the server's own default.
  const [timezones, setTimezones] = useState<string[]>(["Asia/Kolkata"]);

  const [values, setValues] = useState<RegistrationFormValues>(() => ({
    ...emptyRegistrationForm,
    timezone: "Asia/Kolkata",
  }));
  const [errors, setErrors] = useState<RegistrationFormErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetchAllowedCompanyTimezones().then((allowed) => {
      if (cancelled || allowed.length === 0) return;
      setTimezones(allowed);
      setValues((current) => ({
        ...current,
        timezone: allowed.includes(current.timezone) ? current.timezone : allowed[0],
      }));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  function updateField<K extends keyof RegistrationFormValues>(key: K, value: RegistrationFormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
    setErrors((current) => ({ ...current, [key]: undefined }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    const clientErrors = validateRegistrationForm(values);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }

    setSubmitting(true);
    try {
      const payload = buildRegistrationPayload(values);
      const data = await apiClient.post<TokenResponseData>("/companies/register", payload, {
        authenticated: false,
      });
      await applyTokenResponse(data);
      router.push("/app/setup");
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 409) {
          setFormError("An account with this email already exists. Try signing in instead.");
          setErrors((current) => ({ ...current, adminEmail: "Already registered." }));
        } else if (error.status === 422) {
          const nextErrors: RegistrationFormErrors = {
            name: getFieldError(error.details, "name"),
            industryCode: getFieldError(error.details, "industry_code"),
            countryCode: getFieldError(error.details, "country_code"),
            currency: getFieldError(error.details, "currency"),
            timezone: getFieldError(error.details, "timezone"),
            fyStartMonth: getFieldError(error.details, "fy_start_month"),
            companySize: getFieldError(error.details, "company_size"),
            adminFirstName: getFieldError(error.details, "admin_first_name"),
            adminLastName: getFieldError(error.details, "admin_last_name"),
            adminEmail: getFieldError(error.details, "admin_email"),
            adminPassword: getFieldError(error.details, "admin_password"),
          };
          const hasFieldError = Object.values(nextErrors).some(Boolean);
          setErrors(nextErrors);
          setFormError(hasFieldError ? null : error.message);
        } else if (error.status === 429) {
          setFormError("Too many attempts. Please wait a moment and try again.");
        } else {
          setFormError(error.message);
        }
      } else {
        setFormError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout
      title="Register your company"
      description="Create your organisation's workspace and admin account."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-primary hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} noValidate className="space-y-6">
        {formError ? (
          <div role="alert" className="rounded-md border border-danger/30 bg-danger-subtle px-3 py-2 text-sm text-danger">
            {formError}
          </div>
        ) : null}

        <fieldset className="space-y-4" disabled={submitting}>
          <legend className="text-sm font-medium text-foreground">Company details</legend>

          <FormField id="name" label="Company name" required error={errors.name}>
            <Input
              value={values.name}
              onChange={(e) => updateField("name", e.target.value)}
              autoComplete="organization"
              maxLength={200}
            />
          </FormField>

          <FormField id="industryCode" label="Industry" description="Optional" error={errors.industryCode}>
            <Input
              value={values.industryCode}
              onChange={(e) => updateField("industryCode", e.target.value)}
              placeholder="e.g. Manufacturing, IT Services"
              maxLength={40}
            />
          </FormField>

          <div className="grid grid-cols-2 gap-4">
            <FormField id="countryCode" label="Country code" error={errors.countryCode}>
              <Input
                value={values.countryCode}
                onChange={(e) => updateField("countryCode", e.target.value.toUpperCase())}
                maxLength={2}
              />
            </FormField>

            <FormField id="currency" label="Currency" error={errors.currency}>
              <Input
                value={values.currency}
                onChange={(e) => updateField("currency", e.target.value.toUpperCase())}
                maxLength={3}
              />
            </FormField>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <FormField
              id="timezone"
              label="Timezone"
              error={errors.timezone}
              description={
                timezones.length === 1 ? "India-only for now — more regions coming soon." : undefined
              }
            >
              {timezones.length === 1 ? (
                <Input value={timezones[0]} disabled />
              ) : (
                <NativeSelect
                  value={values.timezone}
                  onChange={(e) => updateField("timezone", e.target.value)}
                >
                  {timezones.map((tz) => (
                    <option key={tz} value={tz}>
                      {tz}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </FormField>

            <FormField id="fyStartMonth" label="Financial year starts" error={errors.fyStartMonth}>
              <NativeSelect
                value={values.fyStartMonth}
                onChange={(e) => updateField("fyStartMonth", Number(e.target.value))}
              >
                {MONTHS.map((month, index) => (
                  <option key={month} value={index + 1}>
                    {month}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          </div>

          <FormField id="companySize" label="Company size" description="Optional" error={errors.companySize}>
            <NativeSelect
              value={values.companySize}
              onChange={(e) => updateField("companySize", e.target.value)}
            >
              <option value="">Select a range</option>
              {COMPANY_SIZE_BANDS.map((band) => (
                <option key={band} value={band}>
                  {band} employees
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </fieldset>

        <fieldset className="space-y-4" disabled={submitting}>
          <legend className="text-sm font-medium text-foreground">Admin account</legend>

          <div className="grid grid-cols-2 gap-4">
            <FormField id="adminFirstName" label="First name" required error={errors.adminFirstName}>
              <Input
                value={values.adminFirstName}
                onChange={(e) => updateField("adminFirstName", e.target.value)}
                autoComplete="given-name"
                maxLength={100}
              />
            </FormField>

            <FormField id="adminLastName" label="Last name" required error={errors.adminLastName}>
              <Input
                value={values.adminLastName}
                onChange={(e) => updateField("adminLastName", e.target.value)}
                autoComplete="family-name"
                maxLength={100}
              />
            </FormField>
          </div>

          <FormField id="adminEmail" label="Work email" required error={errors.adminEmail}>
            <Input
              type="email"
              value={values.adminEmail}
              onChange={(e) => updateField("adminEmail", e.target.value)}
              autoComplete="email"
            />
          </FormField>

          <FormField
            id="adminPassword"
            label="Password"
            required
            error={errors.adminPassword}
            description={errors.adminPassword ? undefined : "At least 8 characters, with a letter and a digit."}
          >
            <PasswordInput
              value={values.adminPassword}
              onChange={(e) => updateField("adminPassword", e.target.value)}
              autoComplete="new-password"
            />
          </FormField>

          <FormField id="confirmPassword" label="Confirm password" required error={errors.confirmPassword}>
            <PasswordInput
              value={values.confirmPassword}
              onChange={(e) => updateField("confirmPassword", e.target.value)}
              autoComplete="new-password"
            />
          </FormField>
        </fieldset>

        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? "Creating your workspace…" : "Create workspace"}
        </Button>
      </form>
    </AuthLayout>
  );
}
