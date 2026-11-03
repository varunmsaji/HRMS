import type { Metadata } from "next";

import { Landing } from "@/components/landing/landing";

const title = "Krewoxa HRMS | Organize Your HR Operations";
const description =
  "Discover how Krewoxa helps businesses organize employee information and everyday HR workflows. Book a demo to explore the product.";

export const metadata: Metadata = {
  title,
  description,
  openGraph: { title, description, siteName: "Krewoxa", type: "website" },
  twitter: { card: "summary_large_image", title, description },
};

export default function HomePage() {
  return <Landing />;
}
