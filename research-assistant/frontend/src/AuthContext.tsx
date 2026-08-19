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
}

const AuthContext = createContext<AuthContextValue>({
  session: null,
  loading: true,
  accessToken: null,
  recovering: false,
  completeRecovery: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [recovering, setRecovering] = useState(false);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });

    const { data: listener } = supabase.auth.onAuthStateChange((event, newSession) => {
      setSession(newSession);
      if (event === "PASSWORD_RECOVERY") setRecovering(true);
    });

    return () => listener.subscription.unsubscribe();
  }, []);

  return (
    <AuthContext.Provider
      value={{
        session,
        loading,
        accessToken: session?.access_token ?? null,
        recovering,
        completeRecovery: () => setRecovering(false),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
