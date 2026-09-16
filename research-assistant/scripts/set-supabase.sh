#!/usr/bin/env bash
# Point the app at a Supabase project, and check that it answers.
#
# The keys live in three places (backend auth, frontend client, frontend build)
# and a mismatch between them fails at runtime with a 401 that explains
# nothing — so they are written together, from one source, and verified first.
#
#   ./scripts/set-supabase.sh https://abcd1234.supabase.co eyJhbGciOi...
#
# Both values are on the Supabase dashboard under Settings -> API:
#   URL      = "Project URL"
#   ANON KEY = "anon public"   (safe in a browser; NOT the service_role key)

set -euo pipefail

URL="${1:-}"
ANON="${2:-}"

if [[ -z "$URL" || -z "$ANON" ]]; then
  echo "usage: $0 <project-url> <anon-key>" >&2
  exit 1
fi

URL="${URL%/}"

if [[ ! "$URL" =~ ^https://[a-z0-9-]+\.supabase\.co$ ]]; then
  echo "error: '$URL' does not look like a Supabase project URL" >&2
  exit 1
fi

# The service_role key bypasses every row-level security policy. Putting it in
# a frontend .env ships it to every visitor, so refuse it outright.
if [[ "$ANON" == *"service_role"* ]]; then
  echo "error: that looks like the service_role key. Use the 'anon public' key —" >&2
  echo "       service_role bypasses RLS and must never reach a browser." >&2
  exit 1
fi

HOST="${URL#https://}"
echo "Checking $HOST responds..."
# On a DNS failure curl prints "000" AND exits non-zero, so a `|| echo 000`
# fallback appends a second line and the result stops equalling "000" — which
# is how the first version of this check waved a deleted project through and
# wrote its config anyway. Match a real status code instead of comparing
# against a sentinel.
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$URL/auth/v1/health" 2>/dev/null | tail -n1 || true)
if [[ ! "$CODE" =~ ^[1-5][0-9][0-9]$ ]]; then
  echo "error: no response from $HOST." >&2
  echo "       Check the URL. If the project was deleted, create a new one —" >&2
  echo "       a deleted project stops resolving in DNS entirely." >&2
  exit 1
fi
echo "  responded (HTTP $CODE)"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

set_var() {   # file, key, value
  local file="$1" key="$2" value="$3"
  touch "$file"
  if grep -q "^${key}=" "$file"; then
    # Rewrite via a temp file: `sed -i` takes different arguments on GNU and
    # BSD, and this script has to work on both.
    grep -v "^${key}=" "$file" > "$file.tmp"
    printf '%s=%s\n' "$key" "$value" >> "$file.tmp"
    mv "$file.tmp" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
  echo "  $(basename "$(dirname "$file")")/$(basename "$file"): $key"
}

echo "Writing config..."
set_var "$ROOT/backend/.env"  SUPABASE_URL           "$URL"
set_var "$ROOT/frontend/.env" VITE_SUPABASE_URL      "$URL"
set_var "$ROOT/frontend/.env" VITE_SUPABASE_ANON_KEY "$ANON"

cat <<DONE

Done. Next:
  1. Restart the backend so it fetches the new project's JWKS.
  2. Restart 'npm run dev' — Vite only reads .env at startup.
  3. Sign up through the app to confirm it works end to end.

Guest mode keeps working either way; it never touched Supabase.
DONE
