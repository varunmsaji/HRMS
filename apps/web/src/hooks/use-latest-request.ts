"use client";

import { useCallback, useEffect, useRef } from "react";

/** True for the rejection `apiClient` produces when a request is cancelled through `signal`. */
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export interface LatestRequest {
  signal: AbortSignal;
  /** False once a newer request began or the component unmounted — drop the result. */
  isCurrent: () => boolean;
}

/** Request sequencing for a list or search that can be re-triggered faster than the server
 * answers. `begin()` cancels the previous request and returns a handle for the new one, so an
 * older (slower) response can never overwrite a newer one, and nothing updates state after
 * unmount. The in-flight request is also aborted on unmount. */
export function useLatestRequest(): () => LatestRequest {
  const current = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      current.current?.abort();
    },
    [],
  );

  return useCallback(() => {
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    return {
      signal: controller.signal,
      isCurrent: () =>
        current.current === controller && !controller.signal.aborted,
    };
  }, []);
}
