"use client";

import {
  AlertTriangle,
  Briefcase,
  CalendarCheck,
  Check,
  CheckCircle2,
  ClipboardCheck,
  ClipboardList,
  FileText,
  GraduationCap,
  Lock,
  Landmark,
  MapPin,
  Pencil,
  Phone,
  Upload,
  User,
  Users,
  type LucideIcon,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Logo } from "@/components/brand/logo";
import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
import { AddressInfoStep } from "@/components/onboarding/wizard/address-info-step";
import { BankInfoStep } from "@/components/onboarding/wizard/bank-info-step";
import { DocumentUploadStep } from "@/components/onboarding/wizard/document-upload-step";
import { EducationInfoStep } from "@/components/onboarding/wizard/education-info-step";
import { EmergencyContactStep } from "@/components/onboarding/wizard/emergency-contact-step";
import { NomineeInfoStep } from "@/components/onboarding/wizard/nominee-info-step";
import { PersonalInfoStep } from "@/components/onboarding/wizard/personal-info-step";
import { PreviousEmploymentStep } from "@/components/onboarding/wizard/previous-employment-step";
import { StatutoryInfoStep } from "@/components/onboarding/wizard/statutory-info-step";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, describeLifecycleError } from "@/lib/api/errors";
import type { OnboardingDocument, PublicOnboardingCase } from "@/lib/onboarding/types";
import {
  EMPTY_ADDRESS_INFO,
  EMPTY_BANK_INFO,
  EMPTY_EDUCATION_INFO,
  EMPTY_EMERGENCY_CONTACT,
  EMPTY_NOMINEE_INFO,
  EMPTY_PERSONAL_INFO,
  EMPTY_PREVIOUS_EMPLOYMENT_INFO,
  EMPTY_STATUTORY_INFO,
  addressInfoFromSection,
  addressInfoToPayload,
  bankInfoFromSection,
  bankInfoToPayload,
  educationFromSection,
  educationToPayload,
  emergencyContactFromSection,
  emergencyContactToPayload,
  nomineeFromSection,
  nomineeToPayload,
  personalInfoFromSection,
  personalInfoToPayload,
  previousEmploymentFromSection,
  previousEmploymentToPayload,
  statutoryInfoFromSection,
  statutoryInfoToPayload,
  validateAddressInfo,
  validateBankInfo,
  validateEducation,
  validateEmergencyContact,
  validateNominee,
  validatePersonalInfo,
  validatePreviousEmployment,
  validateStatutoryInfo,
  type AddressInfoFormValues,
  type BankInfoFormValues,
  type EducationFormValues,
  type EmergencyContactFormValues,
  type NomineeFormValues,
  type PersonalInfoFormValues,
  type PreviousEmploymentFormValues,
  type StatutoryInfoFormValues,
} from "@/lib/onboarding/public-wizard";

const STEPS = [
  "welcome",
  "personal",
  "address",
  "emergency",
  "bank",
  "statutory",
  "previousEmployment",
  "education",
  "nominee",
  "documents",
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
  previousEmployment: "Previous Employment",
  education: "Education",
  nominee: "Nominees & Family",
  documents: "Document Upload",
  review: "Review & Submit",
};

const STEP_ICONS: Record<Step, LucideIcon> = {
  welcome: ClipboardList,
  personal: User,
  address: MapPin,
  emergency: Phone,
  bank: Landmark,
  statutory: FileText,
  previousEmployment: Briefcase,
  education: GraduationCap,
  nominee: Users,
  documents: Upload,
  review: ClipboardCheck,
};

const STEP_DESCRIPTIONS: Partial<Record<Step, string>> = {
  personal: "Basic details HR needs for your employee record.",
  address: "Where you currently live.",
  emergency: "Who we should contact if something happens at work.",
  bank: "Where your salary will be paid.",
  statutory: "Tax and statutory registration details.",
  previousEmployment: "Help HR carry forward your PF account from a past employer, if any.",
  education: "Your educational qualifications.",
  nominee: "Your PF/Gratuity nominees and ESI-covered family members.",
  documents: "Upload your ID and any other requested documents.",
};

function WizardHeader() {
  return (
    <header className="border-b border-border bg-surface px-4 py-3.5 sm:px-8">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-3">
        <Logo size={28} />
        <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-3 py-1 text-xs font-medium text-foreground-secondary">
          <Lock className="h-3.5 w-3.5 text-success" aria-hidden="true" />
          Secure onboarding
        </span>
      </div>
    </header>
  );
}

function formatJoiningDate(value: string): string | null {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });
}

function WizardHero({ name, joiningDate }: { name: string; joiningDate: string }) {
  const joining = formatJoiningDate(joiningDate);
  return (
    <section className="relative overflow-hidden rounded-2xl bg-[#0b1530] shadow-sm">
      <Image src="/landing/team.jpg" alt="" fill priority sizes="1152px" className="object-cover" />
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-gradient-to-r from-[#0b1530]/95 via-[#0b1530]/80 to-[#0b1530]/40"
      />
      <div className="relative z-10 px-6 py-8 sm:px-10 sm:py-10">
        <p className="text-sm font-medium text-blue-300">Pre-joining onboarding</p>
        <h1 className="mt-1.5 text-2xl font-semibold tracking-tight text-white sm:text-[32px]">
          Welcome aboard, {name}
        </h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-slate-300 sm:text-base">
          A few details now means a smooth first day. Fill in each section at your own pace — your
          progress is saved as you go.
        </p>
        {joining ? (
          <div className="mt-5 inline-flex items-center gap-2 rounded-lg border border-white/15 bg-white/10 px-3.5 py-2 text-sm text-white backdrop-blur-sm">
            <CalendarCheck className="h-4 w-4 text-blue-300" aria-hidden="true" />
            Proposed joining date: <strong className="font-semibold">{joining}</strong>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function StepNav({ step }: { step: Step }) {
  const currentIndex = STEPS.indexOf(step);
  return (
    <nav aria-label="Onboarding sections" className="hidden lg:block">
      <ol className="space-y-1">
        {STEPS.map((item, index) => {
          const done = index < currentIndex;
          const active = index === currentIndex;
          const Icon = STEP_ICONS[item];
          return (
            <li
              key={item}
              aria-current={active ? "step" : undefined}
              className={
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm " +
                (active
                  ? "bg-primary-subtle font-semibold text-primary"
                  : done
                    ? "text-foreground-secondary"
                    : "text-foreground-muted")
              }
            >
              <span
                className={
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full " +
                  (done
                    ? "bg-success text-white"
                    : active
                      ? "bg-primary text-white"
                      : "border border-border bg-surface")
                }
              >
                {done ? (
                  <Check className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                )}
              </span>
              <span className="truncate">{STEP_LABELS[item]}</span>
              {done ? <span className="sr-only">(completed)</span> : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function TerminalScreen({
  icon: Icon,
  tone,
  title,
  description,
}: {
  icon: LucideIcon;
  tone: "success" | "neutral" | "danger";
  title: string;
  description: string;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <WizardHeader />
      <main className="flex flex-1 items-center justify-center px-4 py-12">
        <div className="w-full max-w-md rounded-lg border border-border bg-surface p-6 text-center shadow-sm sm:p-8">
          <span
            className={
              "mx-auto flex h-12 w-12 items-center justify-center rounded-full " +
              (tone === "success"
                ? "bg-success-subtle text-success"
                : tone === "danger"
                  ? "bg-danger-subtle text-danger"
                  : "bg-muted text-foreground-secondary")
            }
          >
            <Icon className="h-6 w-6" aria-hidden="true" />
          </span>
          <h1 className="mt-4 text-lg font-semibold text-foreground">{title}</h1>
          <p className="mt-2 text-sm text-foreground-secondary">{description}</p>
        </div>
      </main>
    </div>
  );
}

function SectionReviewBanner({ status, reason }: { status: string | undefined; reason: string | null | undefined }) {
  if (status === "VERIFIED") {
    return (
      <div className="mb-6 flex items-start gap-2 rounded-md border border-success bg-success-subtle px-3 py-2 text-sm text-foreground">
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
        This section has been verified by HR — no changes needed.
      </div>
    );
  }
  if (status === "REJECTED") {
    return (
      <div className="mb-6 flex items-start gap-2 rounded-md border border-danger bg-danger-subtle px-3 py-2 text-sm text-foreground">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden="true" />
        HR requested changes to this section{reason ? `: ${reason}` : "."}
      </div>
    );
  }
  return null;
}

function StepHeading({ step }: { step: Step }) {
  const Icon = STEP_ICONS[step];
  const description = STEP_DESCRIPTIONS[step];
  return (
    <div className="mb-6 flex items-start gap-3">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary-subtle text-primary">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <div>
        <h2 className="text-lg font-semibold text-foreground">{STEP_LABELS[step]}</h2>
        {description ? <p className="mt-0.5 text-sm text-foreground-secondary">{description}</p> : null}
      </div>
    </div>
  );
}

function ProgressHeader({ step }: { step: Step }) {
  const currentIndex = STEPS.indexOf(step);
  const pct = Math.round((currentIndex / (STEPS.length - 1)) * 100);
  return (
    <div className="mb-6">
      <div className="mb-2 flex items-center justify-between text-xs font-medium text-foreground-muted">
        <span>
          Step {currentIndex + 1} of {STEPS.length}
        </span>
        <span>{pct}% complete</span>
      </div>
      <Progress value={currentIndex} max={STEPS.length - 1} />
    </div>
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
  const [previousEmployment, setPreviousEmployment] = useState<PreviousEmploymentFormValues>(
    EMPTY_PREVIOUS_EMPLOYMENT_INFO,
  );
  const [educationInfo, setEducationInfo] = useState<EducationFormValues>(EMPTY_EDUCATION_INFO);
  const [nomineeInfo, setNomineeInfo] = useState<NomineeFormValues>(EMPTY_NOMINEE_INFO);
  const [documents, setDocuments] = useState<OnboardingDocument[]>([]);

  const [personalErrors, setPersonalErrors] = useState<
    Partial<Record<keyof PersonalInfoFormValues, string>>
  >({});
  const [addressErrors, setAddressErrors] = useState<
    Partial<Record<keyof AddressInfoFormValues, string>>
  >({});
  const [emergencyErrors, setEmergencyErrors] = useState<
    Partial<Record<keyof EmergencyContactFormValues, string>>
  >({});
  const [bankErrors, setBankErrors] = useState<Partial<Record<keyof BankInfoFormValues, string>>>(
    {},
  );
  const [statutoryErrors, setStatutoryErrors] = useState<
    Partial<Record<keyof StatutoryInfoFormValues, string>>
  >({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, existingDocuments] = await Promise.all([
        apiClient.get<PublicOnboardingCase>(`/public/onboarding/${token}`, {
          authenticated: false,
        }),
        apiClient
          .get<OnboardingDocument[]>(`/public/onboarding/${token}/documents`, {
            authenticated: false,
          })
          .catch(() => []),
      ]);
      setOnboardingCase(data);
      setPersonalInfo(personalInfoFromSection(data.personal_info));
      setAddressInfo(addressInfoFromSection(data.address_info));
      setEmergencyContact(emergencyContactFromSection(data.emergency_contact));
      setBankInfo(bankInfoFromSection(data.bank_info));
      setStatutoryInfo(statutoryInfoFromSection(data.statutory_info));
      setPreviousEmployment(previousEmploymentFromSection(data.previous_employment_info));
      setEducationInfo(educationFromSection(data.education_info));
      setNomineeInfo(nomineeFromSection(data.nominee_info));
      setDocuments(existingDocuments);
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
      toast({ title: "Could not save", description: describeLifecycleError(err), variant: "danger" });
      return false;
    } finally {
      setSaving(false);
    }
  }

  function goTo(next: Step) {
    setStep(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function sectionReviewFor(name: string) {
    return onboardingCase?.section_reviews.find((r) => r.section === name);
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
      <TerminalScreen
        icon={AlertTriangle}
        tone="danger"
        title="Link not available"
        description={
          error?.status === 404
            ? "This onboarding link is invalid or has expired. Please contact HR for a new one."
            : (error?.message ?? "Something went wrong.")
        }
      />
    );
  }

  const candidateName = onboardingCase.candidate_first_name;

  if (submitted || onboardingCase.status === "SUBMITTED" || !onboardingCase.writable) {
    const isSubmitted = onboardingCase.status === "SUBMITTED" || submitted;
    const isActivated = onboardingCase.status === "ACTIVATED";
    return (
      <TerminalScreen
        icon={isSubmitted || isActivated ? CheckCircle2 : AlertTriangle}
        tone={isSubmitted || isActivated ? "success" : "neutral"}
        title={
          isActivated
            ? `You're all set, ${candidateName}!`
            : isSubmitted
              ? `Thanks, ${candidateName}!`
              : "This link is no longer active"
        }
        description={
          isActivated
            ? "Your onboarding is complete and your employee record has been created. Contact HR if anything needs updating."
            : isSubmitted
              ? "Your details have been submitted for review. HR will be in touch if anything needs a correction."
              : `Current status: ${onboardingCase.status}. Please contact HR if you have questions.`
        }
      />
    );
  }

  const reviewSections: {
    step: Step;
    summary: string;
  }[] = [
    {
      step: "personal",
      summary:
        [personalInfo.firstName, personalInfo.lastName].filter(Boolean).join(" ") || "Not filled in yet",
    },
    { step: "address", summary: addressInfo.city ? `City: ${addressInfo.city}` : "Not filled in yet" },
    {
      step: "emergency",
      summary: emergencyContact.contactName
        ? `Contact: ${emergencyContact.contactName}`
        : "Not filled in yet",
    },
    {
      step: "bank",
      summary: bankInfo.paymentMode ? `Payment mode: ${bankInfo.paymentMode}` : "Not filled in yet",
    },
    {
      step: "statutory",
      summary: statutoryInfo.taxRegime ? `Tax regime: ${statutoryInfo.taxRegime}` : "Not filled in yet",
    },
    {
      step: "previousEmployment",
      summary:
        previousEmployment.items.length > 0
          ? `${previousEmployment.items.length} previous employer(s)`
          : "None added",
    },
    {
      step: "education",
      summary:
        educationInfo.items.length > 0
          ? `${educationInfo.items.length} qualification(s)`
          : "None added",
    },
    {
      step: "nominee",
      summary:
        nomineeInfo.items.length > 0 ? `${nomineeInfo.items.length} nominee(s)` : "None added",
    },
    {
      step: "documents",
      summary: documents.length > 0 ? `${documents.length} document(s) uploaded` : "None uploaded yet",
    },
  ];

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <WizardHeader />
      <main className="flex flex-1 justify-center px-4 py-6 sm:px-8 sm:py-10">
        <div className="w-full max-w-6xl space-y-6">
          <WizardHero name={candidateName} joiningDate={onboardingCase.proposed_joining_date} />

          <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
            <aside className="lg:sticky lg:top-6 lg:self-start">
              <div className="rounded-xl border border-border bg-surface p-3 shadow-sm lg:p-4">
                <StepNav step={step} />
                <div className="lg:hidden">
                  <ProgressHeader step={step} />
                  <p className="-mt-3 text-sm font-medium text-foreground">{STEP_LABELS[step]}</p>
                </div>
              </div>
            </aside>

            <div className="min-w-0">
          <div className="rounded-xl border border-border bg-surface p-5 shadow-sm sm:p-8">


            {step === "welcome" ? (
              <div className="space-y-5">
                <div>
                  <h2 className="text-xl font-semibold text-foreground">Let&apos;s get you set up</h2>
                  <p className="mt-1 text-sm text-foreground-secondary">
                    It takes about 10 minutes. Keep these handy before you start:
                  </p>
                </div>
                {onboardingCase.role_summary &&
                (onboardingCase.role_summary.designation ||
                  onboardingCase.role_summary.department ||
                  onboardingCase.role_summary.branch) ? (
                  <section aria-label="Your role" className="rounded-xl border border-border bg-muted/30 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-sm font-semibold text-foreground">Your role &amp; assignment</h3>
                      {onboardingCase.role_summary.company_name ? (
                        <span className="rounded-md border border-border bg-surface px-2.5 py-1 text-xs text-foreground-secondary">
                          {onboardingCase.role_summary.company_name}
                        </span>
                      ) : null}
                    </div>
                    <dl className="mt-3 grid gap-4 sm:grid-cols-3">
                      {[
                        ["Offered designation", onboardingCase.role_summary.designation],
                        ["Department", onboardingCase.role_summary.department],
                        ["Reporting location", onboardingCase.role_summary.branch],
                      ].map(([label, value]) =>
                        value ? (
                          <div key={label}>
                            <dt className="text-2xs font-semibold uppercase tracking-wider text-foreground-muted">
                              {label}
                            </dt>
                            <dd className="mt-1 text-sm font-medium text-foreground">{value}</dd>
                          </div>
                        ) : null,
                      )}
                    </dl>
                  </section>
                ) : null}
                <ul className="grid gap-3 sm:grid-cols-3">
                  {[
                    { icon: Landmark, title: "Bank details", text: "Account number and IFSC, or a cancelled cheque." },
                    { icon: FileText, title: "PF / ESI info", text: "UAN and ESI numbers, if you have them." },
                    { icon: Upload, title: "ID documents", text: "A clear photo or scan of your ID proofs." },
                  ].map(({ icon: Icon, title, text }) => (
                    <li key={title} className="rounded-lg border border-border bg-muted/30 p-4">
                      <span className="flex h-9 w-9 items-center justify-center rounded-md bg-primary-subtle text-primary">
                        <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
                      </span>
                      <p className="mt-3 text-sm font-semibold text-foreground">{title}</p>
                      <p className="mt-1 text-xs leading-relaxed text-foreground-muted">{text}</p>
                    </li>
                  ))}
                </ul>
                <p className="flex items-center gap-2 text-xs text-foreground-muted">
                  <Lock className="h-3.5 w-3.5" aria-hidden="true" />
                  Your information is encrypted and only visible to your HR team.
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
                <StepHeading step="personal" />
                <SectionReviewBanner
                  status={sectionReviewFor("personal_info")?.status}
                  reason={sectionReviewFor("personal_info")?.rejection_reason}
                />
                <PersonalInfoStep
                  values={personalInfo}
                  errors={personalErrors}
                  onChange={setPersonalInfo}
                />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("welcome")}>
                    Back
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={async () => {
                      if (sectionReviewFor("personal_info")?.status === "VERIFIED") {
                        goTo("address");
                        return;
                      }
                      const errors = validatePersonalInfo(personalInfo);
                      setPersonalErrors(errors);
                      if (Object.keys(errors).length > 0) {
                        toast({ title: Object.values(errors)[0], variant: "danger" });
                        return;
                      }
                      const ok = await saveSection("personal_info", personalInfoToPayload(personalInfo));
                      if (ok) goTo("address");
                    }}
                  >
                    {sectionReviewFor("personal_info")?.status === "VERIFIED"
                      ? "Continue"
                      : saving
                        ? "Saving…"
                        : "Save & Continue"}
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "address" ? (
              <div className="space-y-6">
                <StepHeading step="address" />
                <SectionReviewBanner
                  status={sectionReviewFor("address_info")?.status}
                  reason={sectionReviewFor("address_info")?.rejection_reason}
                />
                <AddressInfoStep values={addressInfo} errors={addressErrors} onChange={setAddressInfo} />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("personal")}>
                    Back
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={async () => {
                      if (sectionReviewFor("address_info")?.status === "VERIFIED") {
                        goTo("emergency");
                        return;
                      }
                      const errors = validateAddressInfo(addressInfo);
                      setAddressErrors(errors);
                      if (Object.keys(errors).length > 0) {
                        toast({ title: Object.values(errors)[0], variant: "danger" });
                        return;
                      }
                      const ok = await saveSection("address_info", addressInfoToPayload(addressInfo));
                      if (ok) goTo("emergency");
                    }}
                  >
                    {sectionReviewFor("address_info")?.status === "VERIFIED"
                      ? "Continue"
                      : saving
                        ? "Saving…"
                        : "Save & Continue"}
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "emergency" ? (
              <div className="space-y-6">
                <StepHeading step="emergency" />
                <SectionReviewBanner
                  status={sectionReviewFor("emergency_contact")?.status}
                  reason={sectionReviewFor("emergency_contact")?.rejection_reason}
                />
                <EmergencyContactStep
                  values={emergencyContact}
                  errors={emergencyErrors}
                  onChange={setEmergencyContact}
                />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("address")}>
                    Back
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={async () => {
                      if (sectionReviewFor("emergency_contact")?.status === "VERIFIED") {
                        goTo("bank");
                        return;
                      }
                      const errors = validateEmergencyContact(emergencyContact);
                      setEmergencyErrors(errors);
                      if (Object.keys(errors).length > 0) {
                        toast({ title: Object.values(errors)[0], variant: "danger" });
                        return;
                      }
                      const ok = await saveSection(
                        "emergency_contact",
                        emergencyContactToPayload(emergencyContact),
                      );
                      if (ok) goTo("bank");
                    }}
                  >
                    {sectionReviewFor("emergency_contact")?.status === "VERIFIED"
                      ? "Continue"
                      : saving
                        ? "Saving…"
                        : "Save & Continue"}
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "bank" ? (
              <div className="space-y-6">
                <StepHeading step="bank" />
                <SectionReviewBanner
                  status={sectionReviewFor("bank_info")?.status}
                  reason={sectionReviewFor("bank_info")?.rejection_reason}
                />
                <BankInfoStep values={bankInfo} errors={bankErrors} onChange={setBankInfo} />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("emergency")}>
                    Back
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={async () => {
                      if (sectionReviewFor("bank_info")?.status === "VERIFIED") {
                        goTo("statutory");
                        return;
                      }
                      const errors = validateBankInfo(bankInfo);
                      setBankErrors(errors);
                      if (Object.keys(errors).length > 0) {
                        toast({ title: Object.values(errors)[0], variant: "danger" });
                        return;
                      }
                      const ok = await saveSection("bank_info", bankInfoToPayload(bankInfo));
                      if (ok) goTo("statutory");
                    }}
                  >
                    {sectionReviewFor("bank_info")?.status === "VERIFIED"
                      ? "Continue"
                      : saving
                        ? "Saving…"
                        : "Save & Continue"}
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "statutory" ? (
              <div className="space-y-6">
                <StepHeading step="statutory" />
                <SectionReviewBanner
                  status={sectionReviewFor("statutory_info")?.status}
                  reason={sectionReviewFor("statutory_info")?.rejection_reason}
                />
                <StatutoryInfoStep
                  values={statutoryInfo}
                  errors={statutoryErrors}
                  onChange={setStatutoryInfo}
                />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("bank")}>
                    Back
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={async () => {
                      if (sectionReviewFor("statutory_info")?.status === "VERIFIED") {
                        goTo("previousEmployment");
                        return;
                      }
                      const errors = validateStatutoryInfo(statutoryInfo);
                      setStatutoryErrors(errors);
                      if (Object.keys(errors).length > 0) {
                        toast({ title: Object.values(errors)[0], variant: "danger" });
                        return;
                      }
                      const ok = await saveSection(
                        "statutory_info",
                        statutoryInfoToPayload(statutoryInfo),
                      );
                      if (ok) goTo("previousEmployment");
                    }}
                  >
                    {sectionReviewFor("statutory_info")?.status === "VERIFIED"
                      ? "Continue"
                      : saving
                        ? "Saving…"
                        : "Save & Continue"}
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "previousEmployment" ? (
              <div className="space-y-6">
                <StepHeading step="previousEmployment" />
                <SectionReviewBanner
                  status={sectionReviewFor("previous_employment_info")?.status}
                  reason={sectionReviewFor("previous_employment_info")?.rejection_reason}
                />
                <PreviousEmploymentStep
                  values={previousEmployment}
                  errors={{}}
                  onChange={setPreviousEmployment}
                />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("statutory")}>
                    Back
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={async () => {
                      if (sectionReviewFor("previous_employment_info")?.status === "VERIFIED") {
                        goTo("education");
                        return;
                      }
                      const errors = validatePreviousEmployment(previousEmployment);
                      if (Object.keys(errors).length > 0) {
                        toast({
                          title: errors.items ?? "Fix the previous employment entries",
                          variant: "danger",
                        });
                        return;
                      }
                      const ok = await saveSection(
                        "previous_employment_info",
                        previousEmploymentToPayload(previousEmployment),
                      );
                      if (ok) goTo("education");
                    }}
                  >
                    {sectionReviewFor("previous_employment_info")?.status === "VERIFIED"
                      ? "Continue"
                      : saving
                        ? "Saving…"
                        : "Save & Continue"}
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "education" ? (
              <div className="space-y-6">
                <StepHeading step="education" />
                <SectionReviewBanner
                  status={sectionReviewFor("education_info")?.status}
                  reason={sectionReviewFor("education_info")?.rejection_reason}
                />
                <EducationInfoStep
                  values={educationInfo}
                  errors={{}}
                  onChange={setEducationInfo}
                />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("previousEmployment")}>
                    Back
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={async () => {
                      if (sectionReviewFor("education_info")?.status === "VERIFIED") {
                        goTo("nominee");
                        return;
                      }
                      const errors = validateEducation(educationInfo);
                      if (Object.keys(errors).length > 0) {
                        toast({
                          title: errors.items ?? "Fix the education entries",
                          variant: "danger",
                        });
                        return;
                      }
                      const ok = await saveSection(
                        "education_info",
                        educationToPayload(educationInfo),
                      );
                      if (ok) goTo("nominee");
                    }}
                  >
                    {sectionReviewFor("education_info")?.status === "VERIFIED"
                      ? "Continue"
                      : saving
                        ? "Saving…"
                        : "Save & Continue"}
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "nominee" ? (
              <div className="space-y-6">
                <StepHeading step="nominee" />
                <SectionReviewBanner
                  status={sectionReviewFor("nominee_info")?.status}
                  reason={sectionReviewFor("nominee_info")?.rejection_reason}
                />
                <NomineeInfoStep values={nomineeInfo} errors={{}} onChange={setNomineeInfo} />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("education")}>
                    Back
                  </Button>
                  <Button
                    type="button"
                    disabled={saving}
                    onClick={async () => {
                      if (sectionReviewFor("nominee_info")?.status === "VERIFIED") {
                        goTo("documents");
                        return;
                      }
                      const errors = validateNominee(nomineeInfo);
                      if (Object.keys(errors).length > 0) {
                        toast({
                          title: errors.items ?? "Fix the nominee entries",
                          variant: "danger",
                        });
                        return;
                      }
                      const ok = await saveSection("nominee_info", nomineeToPayload(nomineeInfo));
                      if (ok) goTo("documents");
                    }}
                  >
                    {sectionReviewFor("nominee_info")?.status === "VERIFIED"
                      ? "Continue"
                      : saving
                        ? "Saving…"
                        : "Save & Continue"}
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "documents" ? (
              <div className="space-y-6">
                <StepHeading step="documents" />
                <DocumentUploadStep token={token} documents={documents} onDocumentsChange={setDocuments} />
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("nominee")}>
                    Back
                  </Button>
                  <Button type="button" onClick={() => goTo("review")}>
                    Continue
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "review" ? (
              <div className="space-y-6">
                <StepHeading step="review" />
                <p className="-mt-4 text-sm text-foreground-secondary">
                  Check everything below before you submit. Once submitted, HR will verify each
                  section — you&apos;ll be notified if anything needs a correction.
                </p>
                <div className="space-y-2">
                  {reviewSections.map((section) => {
                    const Icon = STEP_ICONS[section.step];
                    return (
                      <div
                        key={section.step}
                        className="flex items-center justify-between gap-4 rounded-md border border-border p-3"
                      >
                        <div className="flex min-w-0 items-center gap-3">
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-foreground-secondary">
                            <Icon className="h-4 w-4" aria-hidden="true" />
                          </span>
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-foreground">
                              {STEP_LABELS[section.step]}
                            </p>
                            <p className="truncate text-xs text-foreground-muted">{section.summary}</p>
                          </div>
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="shrink-0"
                          onClick={() => goTo(section.step)}
                        >
                          <Pencil aria-hidden="true" />
                          Edit
                        </Button>
                      </div>
                    );
                  })}
                </div>
                <div className="flex justify-between">
                  <Button type="button" variant="outline" onClick={() => goTo("documents")}>
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
              Krewoxa
            </Link>
          </p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
