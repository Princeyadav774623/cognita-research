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
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources: ChatSource[];
}

export interface ChatResponse {
  conversation_id: string;
  answer: string;
  sources: ChatSource[];
}

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body.detail || `Request failed (${res.status})`;
  } catch {
    return `Request failed (${res.status})`;
  }
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

export async function sendChatMessage(
  token: string,
  message: string,
  conversationId: string | null
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/api/rag/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  return res.json();
}
