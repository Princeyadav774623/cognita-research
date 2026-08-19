import { supabase } from "./supabaseClient";

/**
 * Auth operations and the copy that goes with them.
 *
 * Supabase's raw errors are written for developers ("Invalid login
 * credentials", "AuthApiError: User already registered"). Surfacing them
 * directly leaves a person guessing whether they typed the wrong password,
 * never had an account, or hit a rate limit — so every failure is translated
 * into something that says what to do next.
 */

export type AuthMode = "signin" | "signup" | "reset";

export interface AuthResult {
  ok: boolean;
  /** Shown in the error style. */
  error?: string;
  /** Shown in the success/info style. */
  info?: string;
}

/** Maps a Supabase error onto language a person can act on. */
function humanize(raw: string): string {
  const m = raw.toLowerCase();

  if (m.includes("invalid login credentials")) {
    return "That email and password don't match an account. Check the password, or sign up if you're new.";
  }
  if (m.includes("email not confirmed")) {
    return "This account still needs confirming. Check your inbox for the link — or continue with Google instead.";
  }
  if (m.includes("user already registered") || m.includes("already been registered")) {
    return "An account already exists for this email. Sign in instead, or reset the password if you've forgotten it.";
  }
  if (m.includes("password should be at least")) {
    return "Passwords need to be at least 6 characters.";
  }
  if (m.includes("unable to validate email") || m.includes("invalid email")) {
    return "That doesn't look like a valid email address.";
  }
  // Supabase's built-in mailer is tightly rate limited; without this the user
  // sees "email rate limit exceeded" and assumes their account is broken.
  if (m.includes("rate limit") || m.includes("too many requests") || m.includes("for security purposes")) {
    return "Too many attempts just now. Wait a minute and try again — or continue with Google, which doesn't send email.";
  }
  if (m.includes("provider is not enabled")) {
    return "Google sign-in isn't switched on for this deployment yet.";
  }
  if (m.includes("failed to fetch") || m.includes("network")) {
    return "Couldn't reach the server. Check your connection and try again.";
  }
  return raw;
}

export function validate(mode: AuthMode, email: string, password: string): string | null {
  if (!email.trim()) return "Enter your email address.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return "That doesn't look like a valid email address.";
  if (mode === "reset") return null;
  if (!password) return "Enter your password.";
  if (mode === "signup" && password.length < 8) {
    // Supabase's own floor is 6; 8 is the house rule, checked here so the
    // person hears it before a round trip.
    return "Choose a password of at least 8 characters.";
  }
  return null;
}

/** Rough strength signal for the signup field. Deliberately not a gate. */
export function passwordStrength(pw: string): { score: 0 | 1 | 2 | 3; label: string } {
  if (pw.length < 8) return { score: 0, label: "Too short" };
  let score = 0;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  if (score <= 1) return { score: 1, label: "Weak" };
  if (score <= 2) return { score: 2, label: "Good" };
  return { score: 3, label: "Strong" };
}

export async function signIn(email: string, password: string): Promise<AuthResult> {
  const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
  return error ? { ok: false, error: humanize(error.message) } : { ok: true };
}

export async function signUp(email: string, password: string): Promise<AuthResult> {
  const { data, error } = await supabase.auth.signUp({
    email: email.trim(),
    password,
    options: { emailRedirectTo: `${window.location.origin}/` },
  });
  if (error) return { ok: false, error: humanize(error.message) };

  // When confirmation is required Supabase returns a user with no session.
  // When it is switched off, a session comes back and the person is already in.
  if (data.session) return { ok: true };
  return {
    ok: true,
    info: `Almost there — we've sent a confirmation link to ${email.trim()}. Open it, then sign in.`,
  };
}

let googleAvailability: Promise<boolean> | null = null;

/**
 * Whether Google sign-in is actually switched on for this Supabase project.
 *
 * This matters because Supabase's OAuth flow does a full-page redirect to its
 * own /authorize endpoint immediately on click — before any "provider not
 * enabled" error can reach client code. Confirmed against this project: with
 * Google unconfigured, clicking the button lands the visitor on a bare JSON
 * error page (`{"code":400,"error_code":"validation_failed","msg":"Unsupported
 * provider: provider is not enabled"}`) with no way back except the browser's
 * Back button. The fix is to not offer the button until the provider is
 * confirmed enabled, checked against Supabase's own public settings endpoint
 * and cached for the session (it doesn't change while the app is open).
 */
export function checkGoogleEnabled(): Promise<boolean> {
  if (!googleAvailability) {
    const url = import.meta.env.VITE_SUPABASE_URL;
    const key = import.meta.env.VITE_SUPABASE_ANON_KEY;
    googleAvailability = fetch(`${url}/auth/v1/settings`, { headers: { apikey: key } })
      .then((r) => r.json())
      .then((d) => Boolean(d?.external?.google))
      .catch(() => false); // fail closed: hide the button rather than risk the dead end
  }
  return googleAvailability;
}

/**
 * Google OAuth.
 *
 * Also the way around this project's email problem: Google has already
 * verified the address, so no confirmation mail is sent and the provider's
 * per-hour mail limit never applies.
 */
export async function signInWithGoogle(): Promise<AuthResult> {
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: `${window.location.origin}/`,
      // Ask Google for a refresh token and let the person pick an account
      // rather than silently reusing whichever one the browser remembers.
      queryParams: { access_type: "offline", prompt: "select_account" },
    },
  });
  // On success the browser navigates away, so reaching here means it failed.
  return error ? { ok: false, error: humanize(error.message) } : { ok: true };
}

export async function sendPasswordReset(email: string): Promise<AuthResult> {
  const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), {
    redirectTo: `${window.location.origin}/?mode=recovery`,
  });
  if (error) return { ok: false, error: humanize(error.message) };
  // Deliberately not confirming whether the address exists — that would let
  // anyone test which emails have accounts here.
  return {
    ok: true,
    info: `If an account exists for ${email.trim()}, a reset link is on its way.`,
  };
}

export async function updatePassword(password: string): Promise<AuthResult> {
  const { error } = await supabase.auth.updateUser({ password });
  return error
    ? { ok: false, error: humanize(error.message) }
    : { ok: true, info: "Password updated. You're signed in." };
}
