"use client";

import { useRouter, useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PasswordInput } from "@/components/common/password-input";
import { AuthLayout } from "@/components/layout/auth-layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api/client";
import { ApiError, getFieldError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { landingPathFor } from "@/lib/auth/landing";
import type { TokenResponseData } from "@/lib/auth/types";

interface PublicAccountInvite {
  email: string;
  company_name: string;
  expires_at: string;
}

export default function AcceptInvitePage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const router = useRouter();
  const { applyTokenResponse } = useAuth();

  const [loading, setLoading] = useState(true);
  const [invite, setInvite] = useState<PublicAccountInvite | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string | undefined>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await apiClient.get<PublicAccountInvite>(`/public/account-invites/${token}`, {
        authenticated: false,
      });
      setInvite(data);
    } catch (err) {
      setInvite(null);
      setLoadError(
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

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    const nextErrors: Record<string, string | undefined> = {};
    if (password.length < 8 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) {
      nextErrors.password = "At least 8 characters, with a letter and a digit.";
    }
    if (password !== confirmPassword) {
      nextErrors.confirmPassword = "Passwords do not match.";
    }
    if (Object.values(nextErrors).some(Boolean)) {
      setFieldErrors(nextErrors);
      return;
    }

    setSubmitting(true);
    try {
      const data = await apiClient.post<TokenResponseData>(
        `/public/account-invites/${token}/accept`,
        {
          password,
          first_name: firstName.trim() || undefined,
          last_name: lastName.trim() || undefined,
        },
        { authenticated: false },
      );
      const user = await applyTokenResponse(data);
      router.push(landingPathFor(user));
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 409) {
          setFormError(error.message);
        } else if (error.status === 422) {
          setFieldErrors({ password: getFieldError(error.details, "password") });
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

  if (loading) {
    return <LoadingState fullPage label="Loading your invite…" />;
  }

  if (loadError || !invite) {
    return (
      <AuthLayout title="Invite not available">
        <p className="text-center text-sm text-foreground-secondary">
          {loadError?.status === 404
            ? "This invite link is invalid or has expired. Please ask your admin to send a new one."
            : (loadError?.message ?? "Something went wrong.")}
        </p>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title={`Join ${invite.company_name}`}
      description={`Set a password for ${invite.email} to finish creating your account.`}
    >
      <form onSubmit={handleSubmit} noValidate className="space-y-4">
        {formError ? (
          <div
            role="alert"
            className="rounded-md border border-danger/30 bg-danger-subtle px-3 py-2 text-sm text-danger"
          >
            {formError}
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-4">
          <FormField id="firstName" label="First name">
            <Input value={firstName} onChange={(e) => setFirstName(e.target.value)} maxLength={100} />
          </FormField>
          <FormField id="lastName" label="Last name">
            <Input value={lastName} onChange={(e) => setLastName(e.target.value)} maxLength={100} />
          </FormField>
        </div>

        <FormField
          id="password"
          label="Password"
          required
          error={fieldErrors.password}
          description="At least 8 characters, with a letter and a digit."
        >
          <PasswordInput
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              setFieldErrors((current) => ({ ...current, password: undefined }));
            }}
            autoComplete="new-password"
          />
        </FormField>

        <FormField id="confirmPassword" label="Confirm password" required error={fieldErrors.confirmPassword}>
          <PasswordInput
            value={confirmPassword}
            onChange={(e) => {
              setConfirmPassword(e.target.value);
              setFieldErrors((current) => ({ ...current, confirmPassword: undefined }));
            }}
            autoComplete="new-password"
          />
        </FormField>

        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthLayout>
  );
}
