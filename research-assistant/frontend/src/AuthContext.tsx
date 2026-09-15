import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "./supabaseClient";

interface AuthContextValue {
  session: Session | null;
  loading: boolean;
  accessToken: string | null;
  /**
   * True from the moment a password-recovery link is opened until the user
   * sets a new password. Supabase establishes a real, signed-in session for a
   * recovery link — so `session` alone can't gate access to the app, or a
   * reset link would drop the visitor straight past "choose a new password"
   * and into their account.
   */
  recovering: boolean;
  completeRecovery: () => void;
  loginAsGuest: () => void;
  logout: () => Promise<void>;
}

const MOCK_GUEST_SESSION: Session = {
  access_token: "dev-guest-token",
  token_type: "bearer",
  expires_in: 3600 * 24 * 30,
  expires_at: Math.floor(Date.now() / 1000) + 86400 * 30,
  refresh_token: "dev-guest-refresh-token",
  user: {
    id: "dev-guest-user-001",
    app_metadata: {},
    user_metadata: { name: "Guest Researcher" },
    aud: "authenticated",
    created_at: new Date().toISOString(),
    email: "guest@cognita.local",
  },
};

const AuthContext = createContext<AuthContextValue>({
  session: null,
  loading: true,
  accessToken: null,
  recovering: false,
  completeRecovery: () => {},
  loginAsGuest: () => {},
  logout: async () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [recovering, setRecovering] = useState(false);

  useEffect(() => {
    // 1. Check if guest session is active
    if (localStorage.getItem("cognita_guest_mode") === "true") {
      setSession(MOCK_GUEST_SESSION);
      setLoading(false);
      return;
    }

    // 2. Timeout fallback so app never hangs indefinitely on DNS/network errors
    const fallbackTimer = setTimeout(() => {
      setLoading(false);
    }, 2000);

    // 3. Try to get Supabase session
    try {
      supabase.auth.getSession()
        .then(({ data }) => {
          clearTimeout(fallbackTimer);
          if (data?.session) {
            setSession(data.session);
          }
          setLoading(false);
        })
        .catch((err) => {
          clearTimeout(fallbackTimer);
          console.warn("Supabase auth unavailable:", err);
          setLoading(false);
        });

      const { data: listener } = supabase.auth.onAuthStateChange((event, newSession) => {
        if (!localStorage.getItem("cognita_guest_mode")) {
          setSession(newSession);
          if (event === "PASSWORD_RECOVERY") setRecovering(true);
        }
      });

      return () => {
        clearTimeout(fallbackTimer);
        listener?.subscription?.unsubscribe();
      };
    } catch (e) {
      clearTimeout(fallbackTimer);
      setLoading(false);
    }
  }, []);

  const loginAsGuest = () => {
    localStorage.setItem("cognita_guest_mode", "true");
    setSession(MOCK_GUEST_SESSION);
    setLoading(false);
  };

  const logout = async () => {
    localStorage.removeItem("cognita_guest_mode");
    try {
      await supabase.auth.signOut();
    } catch (_) {}
    setSession(null);
  };

  return (
    <AuthContext.Provider
      value={{
        session,
        loading,
        accessToken: session?.access_token ?? null,
        recovering,
        completeRecovery: () => setRecovering(false),
        loginAsGuest,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
