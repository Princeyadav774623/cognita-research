// Empty base = same-origin relative paths, which is what a real deployment
// wants: the browser calls /api/... on the frontend's own origin and nginx
// reverse-proxies to the backend (see nginx.conf), so the backend port never
// has to be publicly reachable. Local `vite dev` sets VITE_API_URL to point
// at http://localhost:8000 directly (see frontend/.env.example).
export const API_BASE = import.meta.env.VITE_API_URL || "";
const WS_BASE = API_BASE
  ? API_BASE.replace(/^http/, "ws")
  : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;

export interface Source {
  title: string;
  url: string;
}

/** A figure published by one of the sources — evidence, not an illustration. */
export interface SourceImage {
  url: string;
  description: string;
  origin_url: string;
}

export interface VerifiedClaim {
  claim: string;
  verified: boolean;
  confidence: number;
  source: string;
  /** Held up against a source the draft was NOT written from. */
  independently_corroborated?: boolean;
}

export interface ResearchResult {
  session_id: string;
  query: string;
  final_report: string;
  sources: Source[];
  images?: SourceImage[];
  confidence: number;
  verified_claims: VerifiedClaim[];
}

export interface SessionRecord extends ResearchResult {
  status: string;
  error: string | null;
  created_at: string;
}

export interface ProgressEvent {
  type: "start" | "progress" | "complete" | "error" | "token";
  /** Present on "token" events — a fragment of the report as it is written. */
  text?: string;
  node?: string;
  step?: string;
  data?: { message?: string; [key: string]: unknown };
  message?: string;
  session_id?: string;
}

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

export async function fetchHistory(token: string, limit = 50): Promise<SessionRecord[]> {
  const res = await fetch(`${API_BASE}/api/history?limit=${limit}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`Failed to load history (${res.status})`);
  const data = await res.json();
  return data.sessions;
}

export async function fetchSession(token: string, sessionId: string): Promise<SessionRecord> {
  const res = await fetch(`${API_BASE}/api/research/${sessionId}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`Session not found (${res.status})`);
  return res.json();
}

export async function deleteSession(token: string, sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/research/${sessionId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(`Failed to delete session (${res.status})`);
}

// Bound the cold-start retries. A host that spins the backend down when idle
// (Render's free tier does so after 15 minutes) refuses the WebSocket
// handshake outright until the instance is back, which takes up to a minute
// — long enough that a single attempt reads as "the app is broken". Eight
// attempts on exponential backoff spread ~60s of waiting across the gap.
const MAX_CONNECT_ATTEMPTS = 8;
const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 15000;

/**
 * Opens the research WebSocket, sends the query + auth token, and streams
 * progress events back through onEvent until completion or error. Browsers
 * can't set custom headers on a WebSocket handshake, so the token rides in
 * the first message payload instead.
 *
 * Retries the handshake on backoff, but only while the server has stayed
 * silent — see `serverSpoke` for why a drop mid-run can't be retried.
 */
export function runResearchStream(
  token: string,
  query: string,
  onEvent: (event: ProgressEvent) => void
): () => void {
  let socket: WebSocket | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let attempts = 0;
  // Once we've received a terminal event, the server closes its end on its
  // own — a client-side close right after that races with the server's
  // close and can surface as a spurious "error" event in the browser even
  // though the research already succeeded. This flag suppresses that noise.
  let finished = false;
  // Whether the server has sent anything on this run. Reconnecting is only
  // safe before it has: the backend reserves a query against the user's
  // monthly quota as soon as the pipeline starts, so a retry after that
  // point would run the research twice and bill for both.
  let serverSpoke = false;
  let cancelled = false;
  let announcedWait = false;

  const connect = () => {
    const ws = new WebSocket(`${WS_BASE}/ws/research`);
    socket = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ query, token }));
    };

    ws.onmessage = (msg) => {
      serverSpoke = true;
      try {
        const event: ProgressEvent = JSON.parse(msg.data);
        if (event.type === "complete" || event.type === "error") {
          finished = true;
        }
        onEvent(event);
      } catch {
        finished = true;
        onEvent({ type: "error", message: "Received malformed message from server" });
      }
    };

    // A refused handshake fires onerror and then onclose, so onclose is the
    // single place that sees every failure — both a backend that isn't up
    // yet and a connection dropped mid-stream — and can tell them apart.
    ws.onclose = () => {
      if (cancelled || finished) return;
      if (serverSpoke) {
        onEvent({
          type: "error",
          message: "Connection lost while researching. Please try again.",
        });
        return;
      }
      scheduleRetry();
    };
  };

  const scheduleRetry = () => {
    attempts += 1;
    if (attempts >= MAX_CONNECT_ATTEMPTS) {
      onEvent({
        type: "error",
        message: "Could not reach the server. Please try again in a moment.",
      });
      return;
    }
    // Announced once rather than per attempt: useResearch appends every
    // progress event to a visible step list, so repeating it would stack up
    // eight identical rows.
    if (!announcedWait) {
      announcedWait = true;
      onEvent({
        type: "progress",
        node: "connect",
        step: "Connecting",
        data: {
          message:
            "Waking up the server — this can take up to a minute after a period of inactivity.",
        },
      });
    }
    const delay = Math.min(
      RECONNECT_BASE_DELAY_MS * 2 ** (attempts - 1),
      RECONNECT_MAX_DELAY_MS
    );
    retryTimer = setTimeout(connect, delay);
  };

  connect();

  return () => {
    cancelled = true;
    if (retryTimer) clearTimeout(retryTimer);
    socket?.close();
  };
}
