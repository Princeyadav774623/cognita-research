import { useEffect, useState } from "react";
import { Icon } from "./Icon";
import { useAuth } from "../AuthContext";
import {
  type AuthMode,
  signIn,
  signUp,
  signInWithGoogle,
  checkGoogleEnabled,
  sendPasswordReset,
  updatePassword,
  validate,
  passwordStrength,
} from "../auth";

/** Google's mark. Inlined because the CSP blocks remote images, and because a
 *  recognisable logo is the whole point of the button. */
function GoogleMark({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <path fill="#4285F4" d="M45.1 24.5c0-1.6-.1-3.2-.4-4.7H24v8.9h11.8c-.5 2.7-2 5-4.4 6.6v5.5h7.1c4.2-3.8 6.6-9.5 6.6-16.3z" />
      <path fill="#34A853" d="M24 46c6 0 11-2 14.6-5.3l-7.1-5.5c-2 1.3-4.5 2.1-7.5 2.1-5.8 0-10.7-3.9-12.400-9.2H4.2v5.7C7.8 41.1 15.3 46 24 46z" />
      <path fill="#FBBC05" d="M11.6 28.1c-.5-1.3-.7-2.7-.7-4.1s.3-2.8.7-4.1v-5.7H4.2C2.8 17.1 2 20.4 2 24s.8 6.9 2.2 9.8l7.4-5.7z" />
      <path fill="#EA4335" d="M24 10.7c3.3 0 6.2 1.1 8.5 3.3l6.3-6.3C35 4.1 30 2 24 2 15.3 2 7.8 6.9 4.2 14.2l7.4 5.7c1.7-5.3 6.6-9.2 12.4-9.2z" />
    </svg>
  );
}

const COPY: Record<AuthMode, { title: string; subtitle: string; cta: string }> = {
  signin: {
    title: "Sign in to Cognita",
    subtitle: "Pick up your research where you left off.",
    cta: "Sign in",
  },
  signup: {
    title: "Create your account",
    subtitle: "Run multi-agent research and chat with your own documents.",
    cta: "Create account",
  },
  reset: {
    title: "Reset your password",
    subtitle: "We'll email you a link to choose a new one.",
    cta: "Send reset link",
  },
};

export function AuthScreen({
  theme = "dark",
  onToggleTheme,
}: {
  theme?: "dark" | "light";
  onToggleTheme?: () => void;
}) {
  const [mode, setMode] = useState<AuthMode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [googleBusy, setGoogleBusy] = useState(false);

  // null while checking, so the button never flashes in only to disappear.
  // See checkGoogleEnabled() for why this check exists at all: clicking the
  // button while the provider isn't configured leads to a dead end that this
  // app has no way to intercept once Supabase's redirect has started.
  const [googleEnabled, setGoogleEnabled] = useState<boolean | null>(null);
  useEffect(() => {
    checkGoogleEnabled().then(setGoogleEnabled);
  }, []);

  // Authoritative from AuthContext: Supabase fires a PASSWORD_RECOVERY auth
  // event (with a real signed-in session attached) when a reset link is
  // opened, and App.tsx renders this screen instead of the main app for as
  // long as this stays true.
  const { recovering, completeRecovery } = useAuth();

  const clear = () => {
    setError(null);
    setInfo(null);
  };

  const submit = async () => {
    clear();

    if (recovering) {
      if (password.length < 8) {
        setError("Choose a password of at least 8 characters.");
        return;
      }
      setSubmitting(true);
      const r = await updatePassword(password);
      setSubmitting(false);
      if (r.error) {
        setError(r.error);
      } else {
        setInfo(r.info ?? null);
        completeRecovery();
      }
      return;
    }

    const invalid = validate(mode, email, password);
    if (invalid) {
      setError(invalid);
      return;
    }

    setSubmitting(true);
    const r =
      mode === "signin"
        ? await signIn(email, password)
        : mode === "signup"
          ? await signUp(email, password)
          : await sendPasswordReset(email);
    setSubmitting(false);

    if (r.error) setError(r.error);
    else if (r.info) setInfo(r.info);
  };

  const google = async () => {
    clear();
    setGoogleBusy(true);
    const r = await signInWithGoogle();
    // A success navigates away; only a failure gets this far.
    if (r.error) {
      setError(r.error);
      setGoogleBusy(false);
    }
  };

  const switchTo = (next: AuthMode) => {
    setMode(next);
    setPassword("");
    clear();
  };

  const copy = COPY[mode];
  const strength = mode === "signup" && password ? passwordStrength(password) : null;

  if (recovering) {
    return (
      <div className="auth-screen">
        <div className="auth-card">
          <div className="auth-card__logo"><Icon name="spark" size={32} weight={1.4} /></div>
          <h1>Choose a new password</h1>
          <p className="auth-card__subtitle">Then you'll be signed straight in.</p>

          <div className="auth-field">
            <label htmlFor="new-password">New password</label>
            <div className="auth-field__wrap">
              <input
                id="new-password"
                type={showPassword ? "text" : "password"}
                value={password}
                autoComplete="new-password"
                placeholder="At least 8 characters"
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
              />
              <button type="button" className="auth-field__peek"
                onClick={() => setShowPassword((s) => !s)}
                aria-label={showPassword ? "Hide password" : "Show password"}>
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
          </div>

          {error && <p className="auth-card__error"><Icon name="alert" size={15} /> {error}</p>}
          {info && <p className="auth-card__info">{info}</p>}

          <button type="button" className="auth-card__btn" onClick={submit} disabled={submitting || !password}>
            {submitting ? "Saving…" : "Set new password"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        {onToggleTheme && (
          <div className="auth-card__toolbar">
            <button type="button" className="app__theme-toggle" onClick={onToggleTheme}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}>
              <Icon name={theme === "dark" ? "sun" : "moon"} size={17} />
            </button>
          </div>
        )}

        <div className="auth-card__logo"><Icon name="spark" size={32} weight={1.4} /></div>
        <h1>{copy.title}</h1>
        <p className="auth-card__subtitle">{copy.subtitle}</p>

        {mode !== "reset" && googleEnabled && (
          <>
            <button type="button" className="auth-google" onClick={google} disabled={googleBusy}>
              <GoogleMark />
              {googleBusy ? "Opening Google…" : "Continue with Google"}
            </button>
            <div className="auth-divider"><span>or</span></div>
          </>
        )}

        <div className="auth-field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={email}
            autoComplete="email"
            placeholder="you@example.com"
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
        </div>

        {mode !== "reset" && (
          <div className="auth-field">
            <div className="auth-field__label-row">
              <label htmlFor="password">Password</label>
              {mode === "signin" && (
                <button type="button" className="auth-link" onClick={() => switchTo("reset")}>
                  Forgot password?
                </button>
              )}
            </div>
            <div className="auth-field__wrap">
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                value={password}
                autoComplete={mode === "signin" ? "current-password" : "new-password"}
                placeholder={mode === "signup" ? "At least 8 characters" : "Your password"}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
              />
              <button type="button" className="auth-field__peek"
                onClick={() => setShowPassword((s) => !s)}
                aria-label={showPassword ? "Hide password" : "Show password"}>
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>

            {strength && (
              <div className="auth-strength" aria-live="polite">
                <div className="auth-strength__track">
                  <div className={`auth-strength__fill auth-strength__fill--${strength.score}`} />
                </div>
                <span>{strength.label}</span>
              </div>
            )}
          </div>
        )}

        {error && <p className="auth-card__error"><Icon name="alert" size={15} /> {error}</p>}
        {info && <p className="auth-card__info">{info}</p>}

        <button type="button" className="auth-card__btn" onClick={submit} disabled={submitting}>
          {submitting ? "Please wait…" : copy.cta}
        </button>

        <div className="auth-card__foot">
          {mode === "signin" && (
            <>New to Cognita? <button type="button" className="auth-link" onClick={() => switchTo("signup")}>Create an account</button></>
          )}
          {mode === "signup" && (
            <>Already have an account? <button type="button" className="auth-link" onClick={() => switchTo("signin")}>Sign in</button></>
          )}
          {mode === "reset" && (
            <button type="button" className="auth-link" onClick={() => switchTo("signin")}>← Back to sign in</button>
          )}
        </div>

        {mode === "signup" && (
          <p className="auth-card__fine">
            By creating an account you agree to the Terms of Service and Privacy Policy.
          </p>
        )}
      </div>
    </div>
  );
}
