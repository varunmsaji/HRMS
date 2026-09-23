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
  /** Returns the freshly-loaded profile — callers that need to redirect based on permissions
   * right after login (doc 41 Phase 4) can't rely on this hook's own `user` value, since a state
   * update from inside an async callback isn't visible in that same closure until the next
   * render. */
  login: (body: LoginRequest) => Promise<UserProfile | null>;
  /** Registration already returns an authenticated session (C-08) — no separate login step. */
  applyTokenResponse: (tokenResponse: TokenResponseData) => Promise<UserProfile | null>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading", session: null, user: null });

  const loadCurrentUser = useCallback(async (session: StoredSession): Promise<UserProfile | null> => {
    try {
      const me = await apiClient.get<MeResponseData>("/auth/me");
      setState({ status: "authenticated", session, user: me.user });
      return me.user;
    } catch {
      // A 401 whose refresh attempt also failed already cleared the session and dispatched
      // SESSION_EXPIRED_EVENT (which set status "unauthenticated" so the /app layout guard
      // redirects to /login) — don't clobber that back to "authenticated" here. Only a
      // non-auth failure (network blip) should leave the user in the app shell with no
      // profile loaded yet.
      if (loadSession() === null) {
        return null;
      }
      setState({ status: "authenticated", session, user: null });
      return null;
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
      return loadCurrentUser(session);
    },
    [loadCurrentUser],
  );

  const login = useCallback(
    async (body: LoginRequest) => {
      const data = await apiClient.post<TokenResponseData>("/auth/login", body, {
        authenticated: false,
      });
      return applyTokenResponse(data);
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
