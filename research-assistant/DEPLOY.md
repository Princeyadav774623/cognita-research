# Deploying Cognita

Target: a single Linux VPS running `docker compose`, with Supabase hosting
Postgres and auth. Roughly $5–10/month.

## Why a VPS rather than Cloud Run / Lambda

Research queries currently run **~134 seconds** end-to-end (down from 361s, but
still long) and stream progress over a WebSocket held open for the duration.
Serverless container platforms are a poor fit for that shape:

- Cloud Run's default request timeout is **5 minutes**, and it bills per
  request-second — you'd pay for the full wall clock of every query.
- A held-open WebSocket prevents scale-to-zero, removing the main reason to
  pick serverless in the first place.

A plain VPS has no request timeout, handles long-lived WebSockets normally, and
costs the same whether idle or busy. Revisit this after research moves to a job
queue (see "Known limits" below).

---

## 1. Prerequisites

- A VPS with Docker and the compose plugin (Hostinger, Hetzner, DigitalOcean).
- A domain pointed at the VPS's IP (an `A` record).
- Your Supabase project (already provisioned).

## 2. Backend secrets

Copy `.env.example` to `backend/.env` on the server and fill it in. The values
that **must** change from local development:

```bash
ENV=production

# Every origin the browser will load the app from. The default is
# localhost-only, which blocks your own production frontend.
CORS_ORIGINS_RAW=https://yourdomain.com,https://www.yourdomain.com

# Point at your Supabase Postgres. APP_DATABASE_URL must be the
# low-privilege role (no BYPASSRLS) so row-level security applies.
DATABASE_URL=postgresql://...
APP_DATABASE_URL=postgresql://...

SUPABASE_URL=https://<project>.supabase.co
GROQ_API_KEY=...
TAVILY_API_KEY=...
```

Never commit this file — `.gitignore` already excludes `*.env`.

## 3. Frontend build values

`frontend/.env.production` is committed and already correct for this setup:

- `VITE_API_URL` is **empty on purpose**. An empty base makes the browser call
  `/api/...` on its own origin, which nginx reverse-proxies to the backend. The
  same bundle then works on any domain, and the backend port never needs to be
  publicly reachable.
- The Supabase URL and anon key are public by design; row-level security is
  what protects the data, not the secrecy of the anon key.

If you use a separate Supabase project for production, override those two at
build time.

> Vite inlines `VITE_*` at **build** time. Setting them in the runtime
> environment has no effect.

## 4. Deploy

```bash
git clone <your-repo> && cd research-assistant
# put backend/.env in place, then:
docker compose up -d --build
```

The frontend container serves the built SPA on port 80 and proxies `/api/` and
`/ws/` to the backend. The backend is bound to `127.0.0.1:8000` so it is
reachable only from the host — it runs with `--proxy-headers`, and exposing it
publicly would let a caller spoof `X-Forwarded-For` to bypass rate limits.

## 5. TLS

Put Caddy or nginx with certbot in front, terminating TLS and forwarding to the
frontend container on `:3000`. Caddy is the shortest path:

```
yourdomain.com {
    reverse_proxy localhost:3000
}
```

## 6. Before you announce it

- [ ] **Supabase email.** Confirmed against the project's own
      `/auth/v1/settings`: `mailer_autoconfirm` is `false`, so every signup
      needs a confirmation email, and the built-in sender is rate-limited to a
      handful per hour — past that, signups fail with no error shown to the
      user. Either configure custom SMTP (Resend, SendGrid) under
      Authentication → Emails, or turn on "Confirm email" → off under
      Authentication → Providers → Email if you do not want confirmation at
      all. This is dashboard-only; it cannot be set from the repo.
- [ ] **Groq capacity.** The account is on **8,000 tokens/minute**, shared
      across every user. That is the binding constraint on concurrency — two
      simultaneous research queries will contend. The free tier's 10
      queries/month cap limits exposure, but upgrade before promoting the site.
- [ ] **Verify the compose build** on the server. Statically validated on the
      dev machine: `nginx -t` passes on `frontend/nginx.conf` (with the compose
      service name substituted, since `backend` only resolves inside the compose
      network), `docker-compose.yml` parses and asserts correctly, and the
      backend `CMD` carries `--proxy-headers`. What is *not* verified is an
      actual image build and containers talking to each other — no container
      runtime was available — so the first `docker compose build` is still the
      first real test of the images and networking.
- [ ] **Smoke test after deploy:** sign up, upload a document, ask a grounded
      question, run one research query, confirm the report renders.

---

## Known limits

Honest accounting of what is not production-grade yet:

| Area | State |
|---|---|
| Research latency | ~134s/query. Fine for a single user, slow for a product. |
| Concurrency | Bounded by 8,000 TPM shared across all users. |
| Durability | Research runs in-request; a deploy kills in-flight queries. |
| Payments | Backend (checkout + signed webhook) is built, but no Stripe keys are set and **the frontend never calls it** — "Upgrade to Pro" has no handler. Users cannot pay. |
| Evaluation | Golden set in `backend/evals/` — run `python -m evals.run --answers` before shipping retrieval changes. |
| Monitoring | No error tracking. Add Sentry before you have real users. |

The highest-value next step is moving research onto a job queue so a deploy
stops killing in-flight work.
