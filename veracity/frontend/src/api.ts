/** Everything the UI knows about the server. */

export type MediaState =
  | "pending" | "fetching" | "probing" | "extracting"
  | "transcribing" | "chunking" | "ready" | "failed";

export interface Media {
  id: string;
  state: MediaState;
  filename: string | null;
  title: string | null;
  duration: string | null;
  duration_ms: number | null;
  has_video: boolean;
  language: string | null;
  transcription_confidence: number | null;
  error: string | null;
  created_at: string | null;
}

export interface Segment {
  ordinal: number; start_ms: number; end_ms: number;
  at: string; text: string; confidence: number | null;
}

export interface Transcript {
  media_id: string; language: string | null; confidence: number | null;
  confidence_is_derived: boolean; segment_count: number; segments: Segment[];
}

export type Verdict =
  | "supported" | "contradicted" | "unsupported"
  | "unclear_audio" | "not_checkable" | "check_failed";

export interface Claim {
  ordinal: number; at: string; start_ms: number;
  spoken: string; proposition: string;
  verdict: Verdict; verdict_confidence: number | null;
  asr_confidence: number | null; reasoning: string | null;
  independently_corroborated: boolean;
  evidence: { title: string; url: string; snippet: string }[];
}

export interface AskPassage {
  at: string; start_ms: number; end_ms: number; text: string; used: boolean;
}

export interface AskAnswer {
  answered: boolean;
  answer: string;
  passages: AskPassage[];
}

export interface Analysis {
  id: string; mode: "summary" | "deep" | "report";
  state: "queued" | "running" | "complete" | "failed";
  error: string | null;
  summary: string | null;
  key_points: { point: string; start_ms: number | null; at?: string }[];
  topics: { title: string; at?: string; doing?: string | null }[];
  overall_confidence: number | null;
  confidence_factors: { factors: string[]; counts: Record<string, number> } | null;
  perspectives: { claim: string; summary: string; held_by: string; kind: string; at?: string }[];
  tokens_used: number; cost_usd: number;
  claims: Claim[];
}

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    // FastAPI puts the useful sentence in `detail`; showing the raw body
    // instead would put a JSON blob in front of the user.
    let message = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      if (body?.detail) message = typeof body.detail === "string"
        ? body.detail : JSON.stringify(body.detail);
    } catch { /* keep the status line */ }
    throw new Error(message);
  }
  return r.json() as Promise<T>;
}

export const api = {
  list: () => fetch("/api/media").then(json<{ items: Media[]; total: number }>),

  get: (id: string) => fetch(`/api/media/${id}`).then(json<Media>),

  upload: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return fetch("/api/media", { method: "POST", body }).then(json<Media>);
  },

  remove: (id: string) =>
    fetch(`/api/media/${id}`, { method: "DELETE" }).then((r) => {
      if (!r.ok && r.status !== 204) throw new Error(`could not delete (${r.status})`);
    }),

  transcript: (id: string) =>
    fetch(`/api/media/${id}/transcript`).then(json<Transcript>),

  analyses: (id: string) =>
    fetch(`/api/media/${id}/analysis`)
      .then(json<{ items: { id: string; mode: string; state: string }[] }>),

  analyse: (id: string, mode: string) =>
    fetch(`/api/media/${id}/analysis`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    }).then(json<{ id: string; state: string; reused: boolean }>),

  analysis: (mediaId: string, id: string) =>
    fetch(`/api/media/${mediaId}/analysis/${id}`).then(json<Analysis>),

  ask: (mediaId: string, question: string) =>
    fetch(`/api/media/${mediaId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }).then(json<AskAnswer>),
};

/** How a verdict should read. The wording matters more than the colour. */
export const VERDICTS: Record<Verdict, { label: string; tone: string; means: string }> = {
  supported: {
    label: "Supported", tone: "ok",
    means: "Independent sources found for this claim agree with it.",
  },
  contradicted: {
    label: "Contradicted", tone: "bad",
    means: "Independent sources state something incompatible with this.",
  },
  unsupported: {
    label: "Not established", tone: "warn",
    means: "The sources found did not settle this either way. That is not the same as false.",
  },
  unclear_audio: {
    label: "Unclear audio", tone: "mute",
    means: "Not checked: the transcriber was not confident about these words, and verifying a misheard sentence would be worse than not checking it.",
  },
  not_checkable: {
    label: "Not checkable", tone: "mute",
    means: "An opinion, prediction or value judgement — evidence cannot settle it.",
  },
  check_failed: {
    label: "Check failed", tone: "warn",
    means: "This one was not checked — a request failed. It is not a finding either way; re-run to pick it up.",
  },
};
