import { useState } from "react";
import { supabase } from "../supabaseClient";
import { Icon } from "./Icon";

export function AuthScreen({
  theme = "dark",
  onToggleTheme,
}: {
  theme?: "dark" | "light";
  onToggleTheme?: () => void;
}) {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    setError(null);
    setInfo(null);
    setSubmitting(true);
    try {
      if (mode === "signin") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
      } else {
        const { error } = await supabase.auth.signUp({ email, password });
        if (error) throw error;
        setInfo("Check your email to confirm your account, then sign in.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-screen">
      <div className="auth-card">
        {onToggleTheme && (
          <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "-1rem" }}>
            <button
              type="button"
              className="app__theme-toggle"
              onClick={onToggleTheme}
              title={`Switch to ${theme === "dark" ? "Light" : "Dark"} mode`}
            >
              <Icon name={theme === "dark" ? "sun" : "moon"} size={17} />
            </button>
          </div>
        )}

        <div className="auth-card__logo"><Icon name="spark" size={34} weight={1.4} /></div>
        <h1>Cognita Research</h1>
        <p className="auth-card__subtitle">
          {mode === "signin"
            ? "Sign in to access your autonomous research workspace"
            : "Create an account to conduct deep multi-agent research"}
        </p>

        <input
          type="email"
          placeholder="Email address"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          autoComplete={mode === "signin" ? "current-password" : "new-password"}
        />

        {error && (
          <p className="auth-card__error">
            <Icon name="alert" size={15} /> {error}
          </p>
        )}
        {info && <p className="auth-card__info">{info}</p>}

        <button
          type="button"
          className="auth-card__btn"
          onClick={submit}
          disabled={submitting || !email || !password}
        >
          {submitting ? "Please wait…" : mode === "signin" ? "Sign In" : "Create Account"}
        </button>

        <button
          type="button"
          className="auth-card__switch"
          onClick={() => {
            setMode(mode === "signin" ? "signup" : "signin");
            setError(null);
            setInfo(null);
          }}
        >
          {mode === "signin"
            ? "Need an account? Sign up"
            : "Already have an account? Sign in"}
        </button>
      </div>
    </div>
  );
}
