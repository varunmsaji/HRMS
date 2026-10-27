"use client";

import { ArrowRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { FormField } from "@/components/common/form-field";
import { PasswordInput } from "@/components/common/password-input";
import { AuthLayout } from "@/components/layout/auth-layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { landingPathFor } from "@/lib/auth/landing";
import { validateLoginForm, type LoginFormErrors } from "@/lib/auth/validate-login";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<LoginFormErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // SEC-09 (RELEASE_HARDENING_PHASE_3A) — shown instead of the generic form error when the
  // credentials are correct but the address hasn't been confirmed yet, with a way to retry.
  const [unverifiedEmail, setUnverifiedEmail] = useState<string | null>(null);
  const [resendState, setResendState] = useState<"idle" | "sending" | "sent">("idle");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setUnverifiedEmail(null);
    setResendState("idle");

    const nextErrors: LoginFormErrors = validateLoginForm({ email, password });

    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors);
      return;
    }

    setSubmitting(true);
    try {
      const user = await login({ email: email.trim(), password });
      router.push(landingPathFor(user));
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "EMAIL_NOT_VERIFIED") {
          setUnverifiedEmail(email.trim());
        } else if (error.status === 401) {
          setFormError("Invalid email or password.");
        } else if (error.status === 423) {
          setFormError("This account is temporarily locked. Try again later.");
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

  async function handleResendVerification() {
    if (!unverifiedEmail) return;
    setResendState("sending");
    try {
      await apiClient.post(
        "/auth/email/resend-verification",
        { email: unverifiedEmail },
        { authenticated: false },
      );
    } finally {
      // Anti-enumeration (matches the backend): always show the same confirmation.
      setResendState("sent");
    }
  }

  return (
    <AuthLayout
      title="Welcome back"
      description="Sign in to your Krewoxa workspace to continue."
      footer={
        <>
          Setting up a new company?{" "}
          <Link href="/register" className="font-semibold text-primary hover:underline">
            Create your workspace
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} noValidate className="space-y-5">
        {formError ? (
          <div role="alert" className="rounded-md border border-danger/30 bg-danger-subtle px-3 py-2 text-sm text-danger">
            {formError}
          </div>
        ) : null}

        {unverifiedEmail ? (
          <div role="alert" className="rounded-md border border-danger/30 bg-danger-subtle px-3 py-2 text-sm text-danger">
            <p>Please verify your email address before signing in.</p>
            {resendState === "sent" ? (
              <p className="mt-1">
                If that address has an account, a new verification email is on its way.
              </p>
            ) : (
              <button
                type="button"
                onClick={handleResendVerification}
                disabled={resendState === "sending"}
                className="mt-1 font-medium underline hover:no-underline disabled:opacity-60"
              >
                {resendState === "sending" ? "Sending…" : "Resend verification email"}
              </button>
            )}
          </div>
        ) : null}

        <FormField id="email" label="Email" required error={errors.email}>
          <Input
            type="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setErrors((current) => ({ ...current, email: undefined }));
            }}
            autoComplete="email"
            placeholder="you@company.com"
            className="h-11 bg-background px-3.5 md:text-base"
            disabled={submitting}
          />
        </FormField>

        <FormField id="password" label="Password" required error={errors.password}>
          <PasswordInput
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              setErrors((current) => ({ ...current, password: undefined }));
            }}
            autoComplete="current-password"
            placeholder="Enter your password"
            className="h-11 bg-background px-3.5 md:text-base"
            disabled={submitting}
          />
        </FormField>

        <div className="-mt-2 text-right text-sm">
          <Link href="/forgot-password" className="font-medium text-primary hover:underline">
            Forgot password?
          </Link>
        </div>

        <Button
          type="submit"
          className="group h-11 w-full text-base font-semibold hover:bg-primary-hover"
          disabled={submitting}
        >
          {submitting ? (
            <>
              <Loader2 className="animate-spin" aria-hidden="true" />
              Signing in…
            </>
          ) : (
            <>
              Sign in
              <ArrowRight className="transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
            </>
          )}
        </Button>
      </form>
    </AuthLayout>
  );
}
