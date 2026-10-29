"use client";

import { useEffect, useState } from "react";

import { DEFAULT_COMPANY_DATE_FORMAT } from "@/lib/dates/company-date";

/**
 * `locale.date_format` is not on the session. Screens use the product default
 * (`DD/MM/YYYY`) until a screen that has loaded the company profile publishes it.
 * Publishing is optional; an unknown or missing pattern still falls back inside
 * `formatCompanyDate`.
 */
let currentPattern = DEFAULT_COMPANY_DATE_FORMAT;
const listeners = new Set<(pattern: string) => void>();

export function rememberCompanyDateFormat(pattern: string | null | undefined): void {
  const next = pattern?.trim();
  if (!next || next === currentPattern) return;
  currentPattern = next;
  listeners.forEach((listener) => listener(next));
}

export function useCompanyDatePattern(): string {
  const [pattern, setPattern] = useState(currentPattern);

  useEffect(() => {
    listeners.add(setPattern);
    return () => {
      listeners.delete(setPattern);
    };
  }, []);

  return pattern;
}
