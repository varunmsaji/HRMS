"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { AuthLayout } from "@/components/layout/auth-layout";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

type Status = "verifying" | "success" | "error";

export default function VerifyEmailPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [status, setStatus] = useState<Status>("verifying");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const attempted = useRef(false);

  useEffect(() => {
    // Guards against React 18 Strict Mode's dev-only double-invoke, which would otherwise burn
    // this single-use token on its own first (harmless but confusing) verification attempt.
    if (attempted.current) return;
    attempted.current = true;

    async function verify() {
      try {
        await apiClient.post("/auth/email/verify", { token }, { authenticated: false });
        setStatus("success");
      } catch (error) {
        setStatus("error");
        if (error instanceof ApiError && error.status === 401) {
          setErrorMessage("This verification link is invalid or has expired.");
        } else {
          setErrorMessage("Something went wrong. Please try again.");
        }
      }
    }
    void verify();
  }, [token]);

  if (status === "verifying") {
    return (
      <AuthLayout title="Verifying your email">
        <p className="text-center text-sm text-foreground-secondary">One moment…</p>
      </AuthLayout>
    );
  }

  if (status === "success") {
    return (
      <AuthLayout title="Email verified">
        <p className="text-center text-sm text-foreground-secondary">
          Your email address has been confirmed. You can now sign in.
        </p>
        <Button asChild className="mt-6 w-full">
          <Link href="/login">Go to sign in</Link>
        </Button>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Verification failed"
      footer={
        <>
          Need a new link?{" "}
          <Link href="/login" className="font-medium text-primary hover:underline">
            Sign in to request one
          </Link>
        </>
      }
    >
      <div role="alert" className="rounded-md border border-danger/30 bg-danger-subtle px-3 py-2 text-sm text-danger">
        {errorMessage}
      </div>
    </AuthLayout>
  );
}
