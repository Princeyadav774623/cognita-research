import { API_BASE } from "./api";

export interface RagDocument {
  id: string;
  filename: string;
  file_type: string;
  status: "processing" | "ready" | "error";
  char_count: number;
  chunk_count: number;
  error: string | null;
  created_at: string;
}

export interface ChatSource {
  filename: string;
  chunk_index: number;
  base_similarity?: number;
  rerank_score?: number;
}

export interface RerankedChunkInfo {
  filename: string;
  chunk_index: number;
  base_similarity: number;
  rerank_score: number;
}

export interface RetrievalStep {
  step: "contextualize" | "retrieve" | "rewrite" | "best_effort" | "give_up";
  query?: string;
  found?: number;
  top_similarity?: number;
  verdict?: string;
  note?: string;
}

export interface EngineeringTelemetry {
  faithfulness_score: number | null;
  answer_relevance: number | null;
  context_precision: number;
  latency_ms: number;
  chunks_retrieved: number;
  chunks_used: number;
  similarity_threshold: number;
  temperature: number;
  model: string;
  reranked: boolean;
  llm_judge?: {
    verdict: string;
    reasoning: string;
    eval_model: string;
    available: boolean;
  } | null;
  reranked_chunks?: RerankedChunkInfo[];
  /** Step-by-step record of how the retrieval loop reached its evidence. */
  retrieval_trace?: RetrievalStep[];
  retrieval_attempts?: number;
  /** True when the agent rewrote its own query and searched again. */
  self_corrected?: boolean;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources: ChatSource[];
  telemetry?: EngineeringTelemetry;
  created_at?: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  message_count: number;
}

export interface ChatResponse {
  conversation_id: string;
  answer: string;
  sources: ChatSource[];
  telemetry?: EngineeringTelemetry;
}

export interface ChatParams {
  top_k?: number;
  temperature?: number;
  similarity_threshold?: number;
}

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

async function parseErrorDetail(res: Response): Promise<string> {
  // Not every error on this path comes from FastAPI as JSON — a reverse proxy
  // in front of the API answers with its own HTML error page (most commonly a
  // 413 when an upload exceeds the proxy's body limit), so blindly reading
  // .detail leaves the user with a bare status code and no idea what to do.
  if (res.status === 413) {
    return "File too large for the server to accept (max 15MB).";
  }
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) {
      // FastAPI request-validation errors arrive as a list of issue objects.
      const first = body.detail[0];
      if (first?.msg) return first.msg;
    }
  } catch {
    // Non-JSON body (proxy error page, gateway timeout, connection reset).
  }
  if (res.status === 502 || res.status === 504) {
    return "The server did not respond in time. It may still be processing — try again shortly.";
  }
  return `Request failed (${res.status})`;
}

export async function uploadDocument(token: string, file: File): Promise<RagDocument> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE}/api/rag/upload`, {
    method: "POST",
    headers: authHeaders(token),
    body: formData,
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json();
}

export async function listDocuments(token: string): Promise<RagDocument[]> {
  const res = await fetch(`${API_BASE}/api/rag/documents`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  const data = await res.json();
  return data.documents;
}

export async function deleteDocument(token: string, id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/rag/documents/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
}

export async function listConversations(token: string): Promise<ConversationSummary[]> {
  const res = await fetch(`${API_BASE}/api/rag/conversations`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  const data = await res.json();
  return data.conversations;
}

export async function getConversation(
  token: string,
  conversationId: string
): Promise<{ conversation_id: string; messages: ChatMessage[] }> {
  const res = await fetch(`${API_BASE}/api/rag/conversations/${conversationId}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json();
}

export async function deleteConversation(token: string, conversationId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/rag/conversations/${conversationId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
}

export async function sendChatMessage(
  token: string,
  message: string,
  conversationId: string | null,
  params?: ChatParams
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/api/rag/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      top_k: params?.top_k ?? 4,
      temperature: params?.temperature ?? 0.2,
      similarity_threshold: params?.similarity_threshold ?? 0.55,
    }),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json();
}
