import type { Metadata } from "next";

import { Landing } from "@/components/landing/landing";

export const metadata: Metadata = {
  title: "Krewoxa HRMS | Organize Your HR Operations",
  description:
    "Discover how Krewoxa helps businesses organize employee information and everyday HR workflows. Book a demo to explore the product.",
};

export default function HomePage() {
  return <Landing />;
}
