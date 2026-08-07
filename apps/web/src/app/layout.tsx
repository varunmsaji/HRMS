import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

/**
 * Body/UI font — 01_Design_System.md §2.2: a grotesk sans with true tabular
 * lining figures built in (not an OpenType feature someone has to remember
 * to enable), required for the payroll/attendance number columns (§2.1).
 * Inter's variable font ships every weight the type scale needs (400-700)
 * from a single download.
 *
 * next/font self-hosts the font files at build time and serves them from
 * our own origin — no runtime request to fonts.googleapis.com — per the
 * "self-contained" performance principle in 00_UI_Vision.md §10, and
 * inlines the correct `font-display` + fallback metrics to avoid layout
 * shift (Next.js's built-in size-adjust fallback).
 *
 * Exposed as a CSS variable (rather than `inter.className` on <body>) so
 * apps/web/tailwind.config.ts can wire it into `fontFamily.sans`, which
 * Tailwind's Preflight then applies globally — the "one config, one
 * source of truth" pattern §2.2 sets up for the future display-face
 * addition (a second `--font-*` variable, added only when that task
 * lands, never replacing this one).
 */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "HRMS Platform",
  description: "Enterprise HRMS — local development",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body>{children}</body>
    </html>
  );
}
