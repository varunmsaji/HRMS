"use client";

import { Copy } from "lucide-react";

import { useToast } from "@/components/common/toast";
import { Button } from "@/components/ui/button";

/**
 * The company code, up front. Employees who sign in with an employee ID instead of an email also
 * need this code, so an admin has to be able to find it and hand it out without hunting through
 * the profile.
 */
export function CompanyCodeCard({ code }: { code: string | null | undefined }) {
  const { toast } = useToast();
  if (!code) return null;

  async function copy() {
    try {
      await navigator.clipboard.writeText(code as string);
      toast({ title: "Company code copied", variant: "success" });
    } catch {
      toast({
        title: "Could not copy",
        description: "Select the code and copy it by hand.",
        variant: "danger",
      });
    }
  }

  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-md border border-primary-border bg-primary-subtle/50 p-4">
      <div className="min-w-0">
        <p className="text-xs font-medium text-foreground-muted">Company code</p>
        <p className="mt-0.5 font-mono text-lg font-semibold text-foreground">{code}</p>
        <p className="mt-1 text-xs text-foreground-secondary">
          Employees who sign in with their employee ID type this code the first time. People
          who sign in with an email do not need it.
        </p>
      </div>
      <Button type="button" variant="outline" size="sm" onClick={() => void copy()}>
        <Copy aria-hidden="true" />
        Copy code
      </Button>
    </div>
  );
}
