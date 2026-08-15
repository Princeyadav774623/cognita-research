const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

export interface Source {
  title: string;
  url: string;
}

export interface VerifiedClaim {
  claim: string;
  verified: boolean;
  confidence: number;
  source: string;
}

export interface ResearchResult {
  session_id: string;
  query: string;
  final_report: string;
  sources: Source[];
  confidence: number;
  verified_claims: VerifiedClaim[];
}

export interface SessionRecord extends ResearchResult {
  status: string;
  error: string | null;
  created_at: string;
}

export interface ProgressEvent {
  type: "start" | "progress" | "complete" | "error";
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

/**
 * Opens the research WebSocket, sends the query + auth token, and streams
 * progress events back through onEvent until completion or error. Browsers
 * can't set custom headers on a WebSocket handshake, so the token rides in
 * the first message payload instead.
 */
export function runResearchStream(
  token: string,
  query: string,
  onEvent: (event: ProgressEvent) => void
): () => void {
  const ws = new WebSocket(`${WS_BASE}/ws/research`);
  // Once we've received a terminal event, the server closes its end on its
  // own — a client-side close right after that races with the server's
  // close and can surface as a spurious "error" event in the browser even
  // though the research already succeeded. This flag suppresses that noise.
  let finished = false;

  ws.onopen = () => {
    ws.send(JSON.stringify({ query, token }));
  };

  ws.onmessage = (msg) => {
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

  ws.onerror = () => {
    if (finished) return;
    onEvent({ type: "error", message: "Connection error" });
  };

  return () => ws.close();
}
