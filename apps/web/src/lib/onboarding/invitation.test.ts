import { describe, expect, it } from "vitest";

import { describeMessageStatus, insertPlaceholder } from "@/lib/onboarding/invitation";
import type { OnboardingMessageStatus } from "@/lib/onboarding/types";

describe("insertPlaceholder", () => {
  it("inserts at the caret and returns the caret after the token", () => {
    expect(insertPlaceholder("Dear ,", 5, 5, "candidate_name")).toEqual({
      value: "Dear {{candidate_name}},",
      caret: 5 + "{{candidate_name}}".length,
    });
  });
  it("replaces a selection", () => {
    expect(insertPlaceholder("Hi NAME!", 3, 7, "candidate_first_name").value).toBe("Hi {{candidate_first_name}}!");
  });
  it("clamps out-of-range offsets", () => {
    expect(insertPlaceholder("ab", 99, 120, "company_name").value).toBe("ab{{company_name}}");
  });
});

describe("describeMessageStatus", () => {
  const all: OnboardingMessageStatus[] = ["NOT_QUEUED", "QUEUED", "RETRYING", "SENDING", "PROVIDER_ACCEPTED", "FAILED", "UNKNOWN"];

  it("never claims inbox delivery", () => {
    for (const status of all) {
      const info = describeMessageStatus(status);
      expect(`${info.label} ${info.description}`.toLowerCase()).not.toMatch(/\bdelivered to\b|\bsent successfully\b/);
    }
    expect(describeMessageStatus("PROVIDER_ACCEPTED").description).toMatch(/does not confirm/i);
  });

  it("only FAILED and NOT_QUEUED require a new invitation; RETRYING is automatic", () => {
    expect(all.filter((s) => describeMessageStatus(s).needsResend)).toEqual(["NOT_QUEUED", "FAILED"]);
    expect(describeMessageStatus("RETRYING").description).toMatch(/same link/i);
  });
});
