import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

import { BackButton } from "@/components/common/back-button";

describe("BackButton", () => {
  it("is a keyboard-focusable link styled as a button with an icon", () => {
    render(<BackButton href="/app/onboarding">Back to onboarding</BackButton>);
    const link = screen.getByRole("link", { name: "Back to onboarding" });
    expect(link).toHaveAttribute("href", "/app/onboarding");
    expect(link.className).toMatch(/border-border/); // outline button styling
    expect(link.className).toMatch(/h-8/); // small button height
    expect(link.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});
