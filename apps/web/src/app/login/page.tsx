"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { FormField } from "@/components/common/form-field";
import { PasswordInput } from "@/components/common/password-input";
import { AuthLayout } from "@/components/layout/auth-layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

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
        if (error.status === 401) {
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

  return (
    <AuthLayout
      title="Sign in"
      description="Welcome back — enter your details to continue."
      footer={
        <>
          Setting up a new company?{" "}
          <Link href="/register" className="font-medium text-primary hover:underline">
            Register
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} noValidate className="space-y-4">
        {formError ? (
          <div role="alert" className="rounded-md border border-danger/30 bg-danger-subtle px-3 py-2 text-sm text-danger">
            {formError}
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
            disabled={submitting}
          />
        </FormField>

        <div className="text-right text-sm">
          <Link href="/forgot-password" className="font-medium text-primary hover:underline">
            Forgot password?
          </Link>
        </div>

        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthLayout>
  );
}
