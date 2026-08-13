"use client";

import { useCallback, useEffect, useState } from "react";

import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

interface UseApiResourceState<T> {
  data: T | null;
  loading: boolean;
  error: ApiError | null;
  /** Distinct from a genuine runtime error when a route returns 404. */
  notImplemented: boolean;
}

/** Shared fetch-on-mount + loading/error/retry for authenticated resource screens. */
export function useApiResource<T>(path: string) {
  const [state, setState] = useState<UseApiResourceState<T>>({
    data: null,
    loading: true,
    error: null,
    notImplemented: false,
  });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState((current) => ({ ...current, loading: true, error: null, notImplemented: false }));

    apiClient
      .get<T>(path)
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null, notImplemented: false });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 404) {
          setState({ data: null, loading: false, error: null, notImplemented: true });
          return;
        }
        setState({
          data: null,
          loading: false,
          error:
            error instanceof ApiError
              ? error
              : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
          notImplemented: false,
        });
      });

    return () => {
      cancelled = true;
    };
  }, [path, reloadToken]);

  const retry = useCallback(() => setReloadToken((token) => token + 1), []);

  return { ...state, retry };
}
