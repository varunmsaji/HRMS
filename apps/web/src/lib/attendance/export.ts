export type CsvCell = string | number | null | undefined;

/** A cell that starts with one of these is read as a formula by Excel and Sheets. A name or a note
 * an employee typed must not run as one, so the cell is prefixed with an apostrophe. Numbers are
 * never touched, so a negative figure stays a figure. */
const FORMULA_START = /^[=+\-@\t\r]/;

export function csvCell(value: CsvCell): string {
  if (value === null || value === undefined) return "";
  const text = typeof value === "number" ? String(value) : FORMULA_START.test(value) ? `'${value}` : value;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** RFC 4180 rows joined by CRLF, with a leading BOM so Excel reads the file as UTF-8. */
export function toCsv(headers: readonly string[], rows: readonly (readonly CsvCell[])[]): string {
  const lines = [headers, ...rows].map((line) => line.map(csvCell).join(","));
  return `﻿${lines.join("\r\n")}\r\n`;
}

/** A safe file name: letters, digits, dash and underscore only. */
export function exportFileName(report: string, rangeLabel: string): string {
  const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `${slug(report)}_${slug(rangeLabel)}.csv`;
}

export function downloadCsv(fileName: string, csv: string): void {
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** The server-built muster register for `query` (the dashboard's own window and filters). The
 * server covers up to a year and only the employees the caller may see, so the file is not limited
 * to the rows this page loaded. */
export function musterRegisterPath(query: Record<string, string>, format: ExportFormat = "csv"): string {
  return `/attendance/export/muster?${new URLSearchParams({ ...query, format }).toString()}`;
}

export type ExportFormat = "csv" | "xlsx" | "pdf";

export const EXPORT_FORMAT_LABELS: Record<ExportFormat, string> = {
  csv: "CSV",
  xlsx: "Excel",
  pdf: "PDF",
};

/** A PDF register is a page of columns: past this many days the server refuses it. */
export const MAX_PDF_REGISTER_DAYS = 62;

export function pdfRegisterError(from: string, to: string): string | null {
  const days = Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000) + 1;
  return days > MAX_PDF_REGISTER_DAYS ? `A PDF register can cover at most ${MAX_PDF_REGISTER_DAYS} days. Choose Excel or CSV for a longer period.` : null;
}

/** The longest period the server will export: a year, to the day. */
export const MAX_EXPORT_DAYS = 366;

export type ServerReport = "daily" | "present-absent" | "late-early" | "hours" | "overtime";

/** The server-built CSV of one report for `query` (a period plus the dashboard's filters). */
export function reportExportPath(report: ServerReport, query: Record<string, string>, format: ExportFormat = "csv"): string {
  return `/attendance/reports/${report}/export?${new URLSearchParams({ ...query, format }).toString()}`;
}

/** Why `from`..`to` cannot be exported, or `null` when it can. ISO dates compare as text. */
export function exportWindowError(from: string, to: string, today: string): string | null {
  if (!from || !to) return "Choose both dates.";
  if (from > to) return "The start date must be on or before the end date.";
  if (to > today) return "The period cannot end in the future.";
  const days = Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000) + 1;
  if (days > MAX_EXPORT_DAYS) return `The period can be at most ${MAX_EXPORT_DAYS} days.`;
  return null;
}

/** Saves a file the API returned (`apiClient.download`), named by the server when it names it. */
export function saveDownloadedFile(file: { blob: Blob; filename: string | null }, fallbackName: string): void {
  const url = URL.createObjectURL(file.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = file.filename ?? fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** One employee's statement for `month` (`YYYY-MM`). */
export function statementPath(employeeId: string, month: string, format: ExportFormat = "pdf"): string {
  return `/attendance/employees/${employeeId}/statement?${new URLSearchParams({ month, format }).toString()}`;
}
