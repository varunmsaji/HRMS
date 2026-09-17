"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { FormField } from "@/components/common/form-field";
import { AuthLayout } from "@/components/layout/auth-layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api/client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!email.trim()) {
      setError("Enter your email address.");
      return;
    }

    setSubmitting(true);
    try {
      // Always the same 202 response whether or not the email matches an account — the API
      // deliberately never discloses account existence here (see identity/service.py's
      // `forgot_password`). The UI mirrors that: one message, no branching on the result.
      await apiClient.post("/auth/password/forgot", { email: email.trim() }, { authenticated: false });
    } finally {
      setSubmitting(false);
      setSent(true);
    }
  }

  if (sent) {
    return (
      <AuthLayout title="Check your email">
        <p className="text-center text-sm text-foreground-secondary">
          If an account exists for <strong>{email.trim()}</strong>, we&apos;ve sent a link to reset
          your password. It expires in 2 hours.
        </p>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Forgot your password?"
      description="Enter your email and we'll send you a reset link."
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
        {error ? (
          <div role="alert" className="rounded-md border border-danger/30 bg-danger-subtle px-3 py-2 text-sm text-danger">
            {error}
          </div>
        ) : null}

        <FormField id="email" label="Email" required>
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            disabled={submitting}
          />
        </FormField>

        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? "Sending…" : "Send reset link"}
        </Button>
      </form>
    </AuthLayout>
  );
}
