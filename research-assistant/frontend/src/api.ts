// Empty base = same-origin relative paths, which is what a real deployment
// wants: the browser calls /api/... on the frontend's own origin and nginx
// reverse-proxies to the backend (see nginx.conf.template), so the backend port never
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
  /** "restart": the run is starting over (a retry, or a server restart) —
   *  progress and streamed text from before it no longer apply. */
  type: "start" | "progress" | "complete" | "error" | "token" | "restart" | "keepalive";
  /** The server's event id; sent back as `after` to resume without repeats. */
  seq?: number;
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

export async function cancelResearch(token: string, sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/research/${sessionId}/cancel`, {
    method: "POST",
    headers: authHeaders(token),
  });
  // 409: it finished before the request landed. Nothing left to stop.
  if (!res.ok && res.status !== 409) throw new Error(`Failed to stop research (${res.status})`);
}

// Bound the reconnect retries. A host that spins the backend down when idle
// (Render's free tier does so after 15 minutes) refuses the WebSocket
// handshake outright until the instance is back, which takes up to a minute
// — long enough that a single attempt reads as "the app is broken". Eight
// consecutive failures on exponential backoff spread ~60s across the gap.
const MAX_CONNECT_ATTEMPTS = 8;
const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 15000;

/**
 * Opens the research WebSocket and streams the run's events back through
 * onEvent until completion or error. Browsers can't set custom headers on a
 * WebSocket handshake, so the token rides in the first message instead.
 *
 * The research runs on the server whether or not this socket is open, so any
 * drop — before the first byte or halfway through the report — is retried.
 * Two things make that safe:
 *   - `sessionId` is chosen here, not by the server. A retry names the same
 *     run, so it attaches to it instead of queueing (and billing) another.
 *   - `after` is the last event id received, so a resumed stream continues
 *     where it left off rather than replaying text already on screen.
 */
export function runResearchStream(
  token: string,
  query: string,
  onEvent: (event: ProgressEvent) => void,
  sessionId: string = crypto.randomUUID()
): () => void {
  let socket: WebSocket | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let attempts = 0;
  let after = 0;
  // Once we've received a terminal event, the server closes its end on its
  // own — a client-side close right after that races with the server's
  // close and can surface as a spurious "error" event in the browser even
  // though the research already succeeded. This flag suppresses that noise.
  let finished = false;
  let cancelled = false;
  let announcedWait = false;

  const connect = () => {
    const ws = new WebSocket(`${WS_BASE}/ws/research`);
    socket = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ token, query, session_id: sessionId, after }));
    };

    ws.onmessage = (msg) => {
      attempts = 0;
      try {
        const event: ProgressEvent = JSON.parse(msg.data);
        if (event.type === "keepalive") return;
        if (typeof event.seq === "number") after = event.seq;
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
    // yet and a connection dropped mid-stream.
    ws.onclose = () => {
      if (cancelled || finished) return;
      scheduleRetry();
    };
  };

  const scheduleRetry = () => {
    attempts += 1;
    if (attempts >= MAX_CONNECT_ATTEMPTS) {
      onEvent({
        type: "error",
        message: "Could not reach the server. Your research is still running — reload to check on it.",
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
          message: "Reconnecting to the server — your research keeps running meanwhile.",
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
