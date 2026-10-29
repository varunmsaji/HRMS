"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  badge?: ReactNode;
  meta?: ReactNode;
  backHref?: string;
  backLabel?: string;
  className?: string;
}

export function PageHeader({
  title,
  description,
  actions,
  badge,
  meta,
  backHref,
  backLabel,
  className,
}: PageHeaderProps) {
  return (
    <div className={cn("border-b border-border pb-4", className)}>
      {backHref ? (
        <div className="mb-2">
          <Link
            href={backHref}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground-secondary transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{backLabel ?? "Back"}</span>
          </Link>
        </div>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
            {badge ? <div className="flex items-center gap-1.5">{badge}</div> : null}
          </div>
          {description ? (
            <p className="mt-1 max-w-3xl text-sm text-foreground-secondary">{description}</p>
          ) : null}
          {meta ? (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-foreground-muted">
              {meta}
            </div>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}
