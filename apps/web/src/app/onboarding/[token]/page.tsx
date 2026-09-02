"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
import { AddressInfoStep } from "@/components/onboarding/wizard/address-info-step";
import { BankInfoStep } from "@/components/onboarding/wizard/bank-info-step";
import { EmergencyContactStep } from "@/components/onboarding/wizard/emergency-contact-step";
import { PersonalInfoStep } from "@/components/onboarding/wizard/personal-info-step";
import { StatutoryInfoStep } from "@/components/onboarding/wizard/statutory-info-step";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import type { PublicOnboardingCase } from "@/lib/onboarding/types";
import {
  EMPTY_ADDRESS_INFO,
  EMPTY_BANK_INFO,
  EMPTY_EMERGENCY_CONTACT,
  EMPTY_PERSONAL_INFO,
  EMPTY_STATUTORY_INFO,
  addressInfoFromSection,
  addressInfoToPayload,
  bankInfoFromSection,
  bankInfoToPayload,
  emergencyContactFromSection,
  emergencyContactToPayload,
  personalInfoFromSection,
  personalInfoToPayload,
  statutoryInfoFromSection,
  statutoryInfoToPayload,
  validateBankInfo,
  validateEmergencyContact,
  validatePersonalInfo,
  validateStatutoryInfo,
  type AddressInfoFormValues,
  type BankInfoFormValues,
  type EmergencyContactFormValues,
  type PersonalInfoFormValues,
  type StatutoryInfoFormValues,
} from "@/lib/onboarding/public-wizard";

const STEPS = [
  "welcome",
  "personal",
  "address",
  "emergency",
  "bank",
  "statutory",
  "review",
] as const;
type Step = (typeof STEPS)[number];

const STEP_LABELS: Record<Step, string> = {
  welcome: "Welcome",
  personal: "Personal Info",
  address: "Address",
  emergency: "Emergency Contact",
  bank: "Bank Details",
  statutory: "Statutory Details",
  review: "Review & Submit",
};

function WizardHeader() {
  return (
    <header className="border-b border-border px-6 py-4">
      <span className="text-md font-semibold text-foreground">HRMS Platform</span>
    </header>
  );
}

function StepIndicator({ step }: { step: Step }) {
  const currentIndex = STEPS.indexOf(step);
  return (
    <ol className="mb-6 flex flex-wrap gap-x-4 gap-y-1 text-xs text-foreground-muted">
      {STEPS.map((s, index) => (
        <li
          key={s}
          className={
            index === currentIndex
              ? "font-medium text-foreground"
              : index < currentIndex
                ? "text-foreground-secondary"
                : undefined
          }
        >
          {index + 1}. {STEP_LABELS[s]}
        </li>
      ))}
    </ol>
  );
}

export default function OnboardingWizardPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const { toast } = useToast();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [onboardingCase, setOnboardingCase] = useState<PublicOnboardingCase | null>(null);
  const [step, setStep] = useState<Step>("welcome");
  const [saving, setSaving] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const [personalInfo, setPersonalInfo] = useState<PersonalInfoFormValues>(EMPTY_PERSONAL_INFO);
  const [addressInfo, setAddressInfo] = useState<AddressInfoFormValues>(EMPTY_ADDRESS_INFO);
  const [emergencyContact, setEmergencyContact] =
    useState<EmergencyContactFormValues>(EMPTY_EMERGENCY_CONTACT);
  const [bankInfo, setBankInfo] = useState<BankInfoFormValues>(EMPTY_BANK_INFO);
  const [statutoryInfo, setStatutoryInfo] = useState<StatutoryInfoFormValues>(EMPTY_STATUTORY_INFO);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<PublicOnboardingCase>(`/public/onboarding/${token}`, {
        authenticated: false,
      });
      setOnboardingCase(data);
      setPersonalInfo(personalInfoFromSection(data.personal_info));
      setAddressInfo(addressInfoFromSection(data.address_info));
      setEmergencyContact(emergencyContactFromSection(data.emergency_contact));
      setBankInfo(bankInfoFromSection(data.bank_info));
      setStatutoryInfo(statutoryInfoFromSection(data.statutory_info));
    } catch (err) {
      setOnboardingCase(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveSection(section: string, payload: Record<string, unknown>): Promise<boolean> {
    setSaving(true);
    try {
      const data = await apiClient.patch<PublicOnboardingCase>(
        `/public/onboarding/${token}/sections/${section}`,
        payload,
        { authenticated: false },
      );
      setOnboardingCase(data);
      return true;
    } catch (err) {
      toast({ title: "Could not save", description: describeApiError(err), variant: "danger" });
      return false;
    } finally {
      setSaving(false);
    }
  }

  function goTo(next: Step) {
    setStep(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function handleSubmit() {
    setSaving(true);
    try {
      const data = await apiClient.post<PublicOnboardingCase>(
        `/public/onboarding/${token}/submit`,
        undefined,
        { authenticated: false },
      );
      setOnboardingCase(data);
      setSubmitted(true);
    } catch (err) {
      toast({
        title: "Could not submit",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <LoadingState fullPage label="Loading your onboarding details…" />;
  }

  if (error || !onboardingCase) {
    return (
      <div className="flex min-h-screen flex-col bg-background">
        <WizardHeader />
        <main className="flex flex-1 items-center justify-center px-4 py-12">
          <div className="w-full max-w-md rounded-lg border border-border bg-surface p-6 text-center shadow-sm sm:p-8">
            <h1 className="text-lg font-semibold text-foreground">Link not available</h1>
            <p className="mt-2 text-sm text-foreground-secondary">
              {error?.status === 404
                ? "This onboarding link is invalid or has expired. Please contact HR for a new one."
                : (error?.message ?? "Something went wrong.")}
            </p>
          </div>
        </main>
      </div>
    );
  }

  const candidateName = onboardingCase.candidate_first_name;

  if (submitted || onboardingCase.status === "SUBMITTED" || !onboardingCase.writable) {
    return (
      <div className="flex min-h-screen flex-col bg-background">
        <WizardHeader />
        <main className="flex flex-1 items-center justify-center px-4 py-12">
          <div className="w-full max-w-md rounded-lg border border-border bg-surface p-6 text-center shadow-sm sm:p-8">
            <h1 className="text-lg font-semibold text-foreground">
              {onboardingCase.status === "SUBMITTED" || submitted
                ? `Thanks, ${candidateName}!`
                : "This link is no longer active"}
            </h1>
            <p className="mt-2 text-sm text-foreground-secondary">
              {onboardingCase.status === "SUBMITTED" || submitted
                ? "Your details have been submitted for review. HR will be in touch if anything needs a correction."
                : `Current status: ${onboardingCase.status}. Please contact HR if you have questions.`}
            </p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <WizardHeader />
      <main className="flex flex-1 justify-center px-4 py-12">
        <div className="w-full max-w-2xl">
          <div className="mb-6">
            <h1 className="text-xl font-semibold text-foreground">Welcome, {candidateName}</h1>
            <p className="mt-1 text-sm text-foreground-secondary">
              Please complete the sections below so HR can finish setting up your employee record.
              You can leave and come back — your progress is saved as you go.
            </p>
          </div>

          <div className="rounded-lg border border-border bg-surface p-6 shadow-sm sm:p-8">
            <StepIndicator step={step} />

            {step === "welcome" ? (
              <div className="space-y-4">
                <p className="text-sm text-foreground-secondary">
                  This should take about 10 minutes. You&apos;ll need your bank account details
                  and PF/ESI information handy.
                </p>
                <div className="flex justify-end">
                  <Button type="button" onClick={() => goTo("personal")}>
                    Get started
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "personal" ? (
              <div className="space-y-6">
                <PersonalInfoStep values={personalInfo} errors={{}} onChange={setPersonalInfo} />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("welcome")}>
                    Back
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={async () => {
                      const errors = validatePersonalInfo(personalInfo);
                      if (Object.keys(errors).length > 0) {
                        toast({ title: "First name is required", variant: "danger" });
                        return;
                      }
                      const ok = await saveSection("personal_info", personalInfoToPayload(personalInfo));
                      if (ok) goTo("address");
                    }}
                  >
                    {saving ? "Saving…" : "Save & Continue"}
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "address" ? (
              <div className="space-y-6">
                <AddressInfoStep values={addressInfo} errors={{}} onChange={setAddressInfo} />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("personal")}>
                    Back
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={async () => {
                      const ok = await saveSection("address_info", addressInfoToPayload(addressInfo));
                      if (ok) goTo("emergency");
                    }}
                  >
                    {saving ? "Saving…" : "Save & Continue"}
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "emergency" ? (
              <div className="space-y-6">
                <EmergencyContactStep values={emergencyContact} errors={{}} onChange={setEmergencyContact} />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("address")}>
                    Back
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={async () => {
                      const errors = validateEmergencyContact(emergencyContact);
                      if (Object.keys(errors).length > 0) {
                        toast({ title: "Contact name and phone are required", variant: "danger" });
                        return;
                      }
                      const ok = await saveSection(
                        "emergency_contact",
                        emergencyContactToPayload(emergencyContact),
                      );
                      if (ok) goTo("bank");
                    }}
                  >
                    {saving ? "Saving…" : "Save & Continue"}
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "bank" ? (
              <div className="space-y-6">
                <BankInfoStep values={bankInfo} errors={{}} onChange={setBankInfo} />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("emergency")}>
                    Back
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={async () => {
                      const errors = validateBankInfo(bankInfo);
                      if (Object.keys(errors).length > 0) {
                        toast({ title: "Payment mode is required", variant: "danger" });
                        return;
                      }
                      const ok = await saveSection("bank_info", bankInfoToPayload(bankInfo));
                      if (ok) goTo("statutory");
                    }}
                  >
                    {saving ? "Saving…" : "Save & Continue"}
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "statutory" ? (
              <div className="space-y-6">
                <StatutoryInfoStep values={statutoryInfo} errors={{}} onChange={setStatutoryInfo} />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("bank")}>
                    Back
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={async () => {
                      const errors = validateStatutoryInfo(statutoryInfo);
                      if (Object.keys(errors).length > 0) {
                        toast({ title: "Tax regime is required", variant: "danger" });
                        return;
                      }
                      const ok = await saveSection(
                        "statutory_info",
                        statutoryInfoToPayload(statutoryInfo),
                      );
                      if (ok) goTo("review");
                    }}
                  >
                    {saving ? "Saving…" : "Save & Continue"}
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "review" ? (
              <div className="space-y-6">
                <p className="text-sm text-foreground-secondary">
                  Please review your details below. Once submitted, HR will verify each section —
                  you&apos;ll be notified if anything needs a correction.
                </p>
                <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
                  <div>
                    <dt className="text-xs font-medium uppercase text-foreground-muted">Name</dt>
                    <dd className="text-foreground">
                      {[personalInfo.firstName, personalInfo.lastName].filter(Boolean).join(" ")}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase text-foreground-muted">City</dt>
                    <dd className="text-foreground">{addressInfo.city || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase text-foreground-muted">
                      Emergency contact
                    </dt>
                    <dd className="text-foreground">{emergencyContact.contactName || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase text-foreground-muted">
                      Payment mode
                    </dt>
                    <dd className="text-foreground">{bankInfo.paymentMode || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium uppercase text-foreground-muted">
                      Tax regime
                    </dt>
                    <dd className="text-foreground">{statutoryInfo.taxRegime || "—"}</dd>
                  </div>
                </dl>
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("statutory")}>
                    Back
                  </Button>
                  <Button type="button" disabled={saving} onClick={() => void handleSubmit()}>
                    {saving ? "Submitting…" : "Submit"}
                  </Button>
                </div>
              </div>
            ) : null}
          </div>

          <p className="mt-4 text-center text-xs text-foreground-muted">
            Having trouble? Contact your HR team.{" "}
            <Link href="/" className="underline">
              HRMS Platform
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
}
