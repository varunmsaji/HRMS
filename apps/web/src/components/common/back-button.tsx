import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";

interface BackButtonProps {
  href: string;
  /** Visible text, e.g. "Back to onboarding". */
  children: React.ReactNode;
}

/** A real, focusable button-styled link for "go back to the list" actions (outline variant with
 * a leading arrow), instead of a bare text link. */
export function BackButton({ href, children }: BackButtonProps) {
  return (
    <Button asChild variant="outline" size="sm">
      <Link href={href}>
        <ArrowLeft aria-hidden="true" />
        {children}
      </Link>
    </Button>
  );
}
