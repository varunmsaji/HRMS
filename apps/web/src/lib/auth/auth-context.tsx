"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { apiClient } from "@/lib/api/client";
import {
  clearSession,
  loadSession,
  saveSession,
  sessionFromTokenResponse,
  SESSION_EXPIRED_EVENT,
  type StoredSession,
} from "@/lib/auth/token-storage";
import type { LoginRequest, MeResponseData, TokenResponseData, UserProfile } from "@/lib/auth/types";

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthState {
  status: AuthStatus;
  session: StoredSession | null;
  user: UserProfile | null;
}

interface AuthContextValue extends AuthState {
  login: (body: LoginRequest) => Promise<void>;
  /** Registration already returns an authenticated session (C-08) — no separate login step. */
  applyTokenResponse: (tokenResponse: TokenResponseData) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading", session: null, user: null });

  const loadCurrentUser = useCallback(async (session: StoredSession) => {
    try {
      const me = await apiClient.get<MeResponseData>("/auth/me");
      setState({ status: "authenticated", session, user: me.user });
    } catch {
      // /auth/me failing for a reason other than an expired session (network blip) shouldn't
      // block the user from the app shell — permissions/email just won't be shown yet.
      setState({ status: "authenticated", session, user: null });
    }
  }, []);

  useEffect(() => {
    const existing = loadSession();
    if (existing) {
      void loadCurrentUser(existing);
    } else {
      setState({ status: "unauthenticated", session: null, user: null });
    }
  }, [loadCurrentUser]);

  useEffect(() => {
    function handleExpired() {
      setState({ status: "unauthenticated", session: null, user: null });
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, handleExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleExpired);
  }, []);

  const applyTokenResponse = useCallback(
    async (tokenResponse: TokenResponseData) => {
      const session = sessionFromTokenResponse(tokenResponse);
      saveSession(session);
      await loadCurrentUser(session);
    },
    [loadCurrentUser],
  );

  const login = useCallback(
    async (body: LoginRequest) => {
      const data = await apiClient.post<TokenResponseData>("/auth/login", body, {
        authenticated: false,
      });
      await applyTokenResponse(data);
    },
    [applyTokenResponse],
  );

  const logout = useCallback(async () => {
    try {
      await apiClient.post("/auth/logout");
    } catch {
      // Best-effort server-side revoke — the client-side session is cleared regardless.
    } finally {
      clearSession();
      setState({ status: "unauthenticated", session: null, user: null });
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, login, applyTokenResponse, logout }),
    [state, login, applyTokenResponse, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
