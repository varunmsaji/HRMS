import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ClientErrorListener } from "@/components/common/client-error-listener";
import * as reporter from "@/lib/observability/report-client-error";

describe("ClientErrorListener", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reports unhandled rejections and uncaught errors, and shows nothing", () => {
    const spy = vi.spyOn(reporter, "reportClientError").mockImplementation(() => undefined);
    // Capture the handlers instead of dispatching real events: jsdom forwards a dispatched
    // `error` event to the test runner as an unhandled error.
    const handlers = new Map<string, EventListener>();
    vi.spyOn(window, "addEventListener").mockImplementation((type: string, listener: unknown) => {
      handlers.set(type, listener as EventListener);
    });
    const remove = vi.spyOn(window, "removeEventListener").mockImplementation(() => undefined);

    const { container, unmount } = render(<ClientErrorListener />);
    expect(container).toBeEmptyDOMElement();

    const reason = new Error("boom");
    handlers.get("unhandledrejection")?.({ reason } as unknown as Event);
    expect(spy).toHaveBeenCalledWith(reason, "unhandled_rejection");

    const failure = new Error("crash");
    handlers.get("error")?.({ error: failure, message: "crash" } as unknown as Event);
    expect(spy).toHaveBeenCalledWith(failure, "uncaught");

    unmount();
    expect(remove).toHaveBeenCalledWith("error", handlers.get("error"));
    expect(remove).toHaveBeenCalledWith("unhandledrejection", handlers.get("unhandledrejection"));
  });
});
