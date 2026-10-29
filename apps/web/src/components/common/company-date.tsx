"use client";

import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";

/** Renders one date-only value in the company format. ISO strings stay out of the UI. */
export function CompanyDate({ value }: { value: string | null | undefined }) {
  const pattern = useCompanyDatePattern();
  return formatCompanyDate(value, pattern);
}
