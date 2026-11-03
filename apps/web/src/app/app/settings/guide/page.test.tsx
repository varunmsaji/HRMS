import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SETTINGS_NAV_GROUPS } from "@/components/layout/nav-items";
import { SETTINGS_GUIDE } from "@/lib/settings-guide/types";

import SettingsGuidePage from "./page";

describe("Settings guide", () => {
  it("renders a section for every guided setting", () => {
    render(<SettingsGuidePage />);
    for (const section of SETTINGS_GUIDE.sections) {
      expect(screen.getByRole("heading", { name: section.title, level: 3 })).toBeTruthy();
    }
  });

  it("only links to settings that exist in the Settings navigation", () => {
    const known = new Set(SETTINGS_NAV_GROUPS.flatMap((g) => g.items.map((i) => i.href)));
    for (const section of SETTINGS_GUIDE.sections) {
      expect(known.has(section.href), `${section.title} -> ${section.href}`).toBe(true);
    }
  });

  it("has unique section ids and no empty option text", () => {
    const ids = SETTINGS_GUIDE.sections.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const section of SETTINGS_GUIDE.sections) {
      for (const part of section.parts) {
        for (const item of part.items) {
          expect(item.name.trim()).not.toBe("");
          expect(item.text.trim()).not.toBe("");
        }
      }
    }
  });
});
