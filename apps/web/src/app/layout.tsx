import type { Metadata } from "next";
import { headers } from "next/headers";
import { connection } from "next/server";
import { Inter } from "next/font/google";
import "./globals.css";

import { Providers } from "@/components/providers";

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

/**
 * `metadataBase` turns the relative og:image URL (app/opengraph-image.png) into an absolute one,
 * which link previews require. It comes from the request's host because the web app has no
 * public-URL setting; without it Next.js would fall back to localhost in production.
 */
export async function generateMetadata(): Promise<Metadata> {
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host");
  const proto = h.get("x-forwarded-proto") ?? (host?.startsWith("localhost") ? "http" : "https");
  return {
    title: "Krewoxa",
    description: "Krewoxa — local development",
    metadataBase: host ? new URL(`${proto}://${host}`) : undefined,
  };
}

/**
 * Every page is rendered per request, never prerendered at build time.
 *
 * The strict CSP (`script-src 'nonce-…' 'strict-dynamic'`, middleware.ts) only works if each
 * response's scripts carry *that response's* nonce, and Next.js can only stamp a nonce while it
 * renders for a request. A prerendered page is built once without any request, so its scripts
 * have no nonce, the browser refuses all of them and the page never hydrates (verified on
 * `/login`, `/register`, `/app/**`, the 404 page); it would also be served from cache with a
 * stale nonce. `connection()` is Next's documented way to wait for an incoming request, and
 * placing it in the root layout covers every route and the not-found page. The HTML shells are
 * tiny; the JS/CSS/font assets under `/_next/static` stay immutable-cached.
 */
export default async function RootLayout({ children }: { children: React.ReactNode }) {
  await connection();
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
