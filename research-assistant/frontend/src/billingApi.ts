import { API_BASE } from "./api";

export interface QuotaStatus {
  user_id: string;
  plan_tier: "free" | "pro";
  status: string;
  queries_used: number;
  quota_limit: number;
  remaining_queries: number;
  has_quota: boolean;
  period_end: string | null;
}

export interface CheckoutResult {
  checkout_url: string;
  /**
   * Only present when the server has no Stripe key configured. In that case
   * `checkout_url` is a stub that redirects straight back to the success
   * page without any payment having happened — so the caller must treat
   * `message` as "billing is not live" rather than following the URL.
   */
  message?: string;
}

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

export async function fetchQuota(token: string): Promise<QuotaStatus> {
  const res = await fetch(`${API_BASE}/api/billing/quota`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`Could not load your plan (${res.status})`);
  return res.json();
}

export async function startCheckout(token: string): Promise<CheckoutResult> {
  // The backend's defaults point at localhost, so always send the real
  // origin — otherwise a production checkout would bounce the user to a
  // developer's machine. Both URLs carry a query string because the
  // demo-mode branch appends `&demo_mode=true`.
  const origin = window.location.origin;
  const res = await fetch(`${API_BASE}/api/billing/create-checkout-session`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({
      success_url: `${origin}/?billing=success`,
      cancel_url: `${origin}/?billing=cancel`,
    }),
  });
  if (!res.ok) {
    let detail = `Checkout could not be started (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json();
}
