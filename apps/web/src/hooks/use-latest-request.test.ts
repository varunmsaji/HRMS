import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { isAbortError, useLatestRequest } from "@/hooks/use-latest-request";

describe("useLatestRequest", () => {
  it("cancels the previous request when a new one begins", () => {
    const { result } = renderHook(() => useLatestRequest());
    const first = result.current();
    expect(first.isCurrent()).toBe(true);

    const second = result.current();
    expect(first.signal.aborted).toBe(true);
    expect(first.isCurrent()).toBe(false);
    expect(second.isCurrent()).toBe(true);
  });

  it("aborts the in-flight request on unmount", () => {
    const { result, unmount } = renderHook(() => useLatestRequest());
    const request = result.current();
    unmount();
    expect(request.signal.aborted).toBe(true);
    expect(request.isCurrent()).toBe(false);
  });

  it("recognises an AbortError but not other failures", () => {
    expect(isAbortError(new DOMException("x", "AbortError"))).toBe(true);
    expect(isAbortError(new Error("boom"))).toBe(false);
  });
});
