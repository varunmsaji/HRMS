"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { FormField } from "@/components/common/form-field";
import { PasswordInput } from "@/components/common/password-input";
import { AuthLayout } from "@/components/layout/auth-layout";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

export default function ResetPasswordPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const router = useRouter();

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errors, setErrors] = useState<{ password?: string; confirmPassword?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    const nextErrors: { password?: string; confirmPassword?: string } = {};
    if (password.length < 8 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) {
      nextErrors.password = "At least 8 characters, with a letter and a digit.";
    }
    if (password !== confirmPassword) {
      nextErrors.confirmPassword = "Passwords do not match.";
    }
    if (Object.values(nextErrors).some(Boolean)) {
      setErrors(nextErrors);
      return;
    }

    setSubmitting(true);
    try {
      await apiClient.post(
        "/auth/password/reset",
        { token, password },
        { authenticated: false },
      );
      setDone(true);
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 401) {
          setFormError("This reset link is invalid or has expired. Please request a new one.");
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

  if (done) {
    return (
      <AuthLayout title="Password updated">
        <p className="text-center text-sm text-foreground-secondary">
          Your password has been reset. You can now sign in with your new password.
        </p>
        <Button className="mt-6 w-full" onClick={() => router.push("/login")}>
          Go to sign in
        </Button>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Choose a new password"
      footer={
        <>
          Remembered it?{" "}
          <Link href="/login" className="font-medium text-primary hover:underline">
            Sign in
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

        <FormField
          id="password"
          label="New password"
          required
          error={errors.password}
          description="At least 8 characters, with a letter and a digit."
        >
          <PasswordInput
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              setErrors((current) => ({ ...current, password: undefined }));
            }}
            autoComplete="new-password"
            disabled={submitting}
          />
        </FormField>

        <FormField id="confirmPassword" label="Confirm password" required error={errors.confirmPassword}>
          <PasswordInput
            value={confirmPassword}
            onChange={(e) => {
              setConfirmPassword(e.target.value);
              setErrors((current) => ({ ...current, confirmPassword: undefined }));
            }}
            autoComplete="new-password"
            disabled={submitting}
          />
        </FormField>

        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? "Resetting…" : "Reset password"}
        </Button>
      </form>
    </AuthLayout>
  );
}
