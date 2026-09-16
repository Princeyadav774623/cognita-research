import { useRef, useState, useEffect, useCallback } from "react";
import {
  sendChatMessage,
  listConversations,
  getConversation,
  deleteConversation,
  type ChatMessage,
  type ConversationSummary,
} from "../ragApi";
import { useAuth } from "../AuthContext";
import { Icon } from "./Icon";

interface Props {
  hasDocuments: boolean;
}

function formatPct(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

const STEP_LABEL: Record<string, string> = {
  contextualize: "Resolved follow-up",
  retrieve: "Searched documents",
  rewrite: "Rewrote query",
  best_effort: "Answered best-effort",
  give_up: "No supporting evidence",
};

type Tone = "pass" | "warn" | "fail" | "muted";

function verdictBadge(
  verdict: string | undefined,
  available: boolean | undefined
): { text: string; tone: Tone } {
  // Tone drives background AND text. The badge used to hardcode a green
  // background, so "JUDGE UNAVAILABLE" and outright FAIL both rendered as if
  // the answer had passed.
  if (!available) return { text: "Not evaluated", tone: "muted" };
  if (verdict === "PASS") return { text: "Grounded", tone: "pass" };
  if (verdict === "FAIL") return { text: "Not grounded", tone: "fail" };
  return { text: "Partially grounded", tone: "warn" };
}

export function ChatPanel({ hasDocuments }: Props) {
  const { accessToken } = useAuth();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [activeInspectorIndex, setActiveInspectorIndex] = useState<number | null>(null);

  // Dynamic Engineering Parameters
  const [topK, setTopK] = useState<number>(4);
  const [temperature, setTemperature] = useState<number>(0.2);
  const [similarityThreshold, setSimilarityThreshold] = useState<number>(0.55);

  const listRef = useRef<HTMLDivElement>(null);

  // Load conversation list
  const refreshConversations = useCallback(async () => {
    if (!accessToken) return;
    try {
      const convs = await listConversations(accessToken);
      setConversations(convs);
    } catch {
      // Ignore initial error
    }
  }, [accessToken]);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  // Load conversation messages when switching chats
  const selectConversation = async (convId: string) => {
    if (!accessToken) return;
    setActiveConversationId(convId);
    setError(null);
    try {
      const data = await getConversation(accessToken, convId);
      setMessages(data.messages);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load conversation history");
    }
  };

  const startNewChat = () => {
    setActiveConversationId(null);
    setMessages([]);
    setError(null);
    setActiveInspectorIndex(null);
  };

  const handleDeleteConversation = async (e: React.MouseEvent, convId: string) => {
    e.stopPropagation();
    if (!accessToken) return;
    try {
      await deleteConversation(accessToken, convId);
      if (activeConversationId === convId) {
        startNewChat();
      }
      refreshConversations();
    } catch {
      // Ignore
    }
  };

  // Scroll the message list itself rather than calling scrollIntoView on a
  // sentinel: scrollIntoView walks every scrollable ancestor including
  // <html>, and index.css sets `scroll-behavior: smooth` globally, so it
  // visibly glided the whole page. Starting a new conversation empties
  // `messages`, which re-fired this effect and jumped the window even
  // though there was nothing to scroll to.
  useEffect(() => {
    const list = listRef.current;
    if (!list || messages.length === 0) return;
    list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  const send = async () => {
    const message = input.trim();
    if (!message || sending || !accessToken) return;

    const userMsg: ChatMessage = { role: "user", content: message, sources: [] };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSending(true);
    setError(null);

    try {
      const res = await sendChatMessage(accessToken, message, activeConversationId, {
        top_k: topK,
        temperature,
        similarity_threshold: similarityThreshold,
      });

      if (!activeConversationId) {
        setActiveConversationId(res.conversation_id);
      }

      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: res.answer,
        sources: res.sources,
        telemetry: res.telemetry,
      };

      setMessages((prev) => [...prev, assistantMsg]);
      refreshConversations();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to send message");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="rag-chat-container">
      {/* Left Chat History & Session Switcher */}
      <aside className="rag-chat-history">
        <div className="rag-chat-history__header">
          <button type="button" className="new-chat-btn" onClick={startNewChat}>
            <Icon name="plus" size={15} /> New Conversation
          </button>
        </div>

        <div className="rag-chat-history__list">
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`rag-chat-history__item ${activeConversationId === c.id ? "rag-chat-history__item--active" : ""}`}
              onClick={() => selectConversation(c.id)}
            >
              <div className="rag-chat-history__item-title">{c.title}</div>
              <div className="rag-chat-history__item-meta">
                <span>{c.created_at ? new Date(c.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "Recent"}</span>
                <span>{c.message_count} msgs</span>
                <button
                  type="button"
                  className="history-item__delete"
                  onClick={(e) => handleDeleteConversation(e, c.id)}
                  title="Delete chat"
                >
                  <Icon name="close" size={13} />
                </button>
              </div>
            </div>
          ))}

          {conversations.length === 0 && (
            <div style={{ color: "var(--text-muted)", fontSize: "0.82rem", textAlign: "center", padding: "1.5rem 0.5rem" }}>
              No previous chats found.
            </div>
          )}
        </div>
      </aside>

      {/* Main Conversation Stream & Inspector */}
      <div className="rag-chat-main">
        {/* Top Control Bar with Engineering Settings Trigger */}
        <div className="rag-chat-topbar">
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-secondary)" }}>
              {activeConversationId ? "Active Session" : "New RAG Session"}
            </span>
            <span className="meta-badge meta-badge--sources" style={{ fontSize: "0.68rem" }}>
              Groq · pgvector RAG
            </span>
          </div>

          <button
            type="button"
            className={`paper-action-btn ${showSettings ? "paper-action-btn--active" : ""}`}
            onClick={() => setShowSettings(!showSettings)}
            title="Configure RAG retrieval parameters & re-ranker"
          >
            <Icon name="sliders" size={15} />
            AI Parameter Tuning
          </button>
        </div>

        {/* Dynamic Parameter Settings Drawer */}
        {showSettings && (
          <div className="rag-params-drawer liquid-glass">
            <div style={{ fontWeight: 600, fontSize: "0.88rem", marginBottom: "0.75rem", color: "var(--text-primary)" }}>
              RAG Engineering & Retrieval Hyperparameters
            </div>
            <div className="params-grid">
              <div className="param-item">
                <label>Top-K Chunks: <strong>{topK}</strong></label>
                <input
                  type="range"
                  min="1"
                  max="8"
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                />
              </div>

              <div className="param-item">
                <label>Similarity Threshold: <strong>{similarityThreshold.toFixed(2)}</strong></label>
                <input
                  type="range"
                  min="0.35"
                  max="0.90"
                  step="0.05"
                  value={similarityThreshold}
                  onChange={(e) => setSimilarityThreshold(Number(e.target.value))}
                />
              </div>

              <div className="param-item">
                <label>LLM Temperature: <strong>{temperature.toFixed(2)}</strong></label>
                <input
                  type="range"
                  min="0.0"
                  max="0.7"
                  step="0.05"
                  value={temperature}
                  onChange={(e) => setTemperature(Number(e.target.value))}
                />
              </div>
            </div>
          </div>
        )}

        {/* Chat Messages */}
        <div className="chat-messages" ref={listRef}>
          {messages.length === 0 && (
            <div className="chat-empty">
              <div className="chat-empty__mark">✶</div>
              <h3 className="chat-empty__title">
                {hasDocuments ? "Ask a question about your documents" : "Upload a document to begin"}
              </h3>

              {hasDocuments ? (
                <>
                  <p className="chat-empty__lead">
                    Every answer quotes the passage it came from, so you can check it.
                  </p>
                  {/* Examples do the explaining. A blank box with an
                      instruction above it still leaves a new reader guessing
                      what a good question looks like here. */}
                  <div className="chat-empty__label">Try asking</div>
                  <div className="chat-empty__examples">
                    {[
                      "What does this document say about pricing?",
                      "Summarise the main findings in plain language.",
                      "What limitations do the authors mention?",
                      "Compare the conclusions across these files.",
                    ].map((q) => (
                      <button
                        key={q}
                        type="button"
                        className="chat-empty__example"
                        onClick={() => setInput(q)}
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <p className="chat-empty__lead">
                    Drop a file into the panel on the left. Once it is indexed you can ask
                    questions about it and every answer will cite the passage it came from.
                  </p>
                  <div className="chat-empty__label">Accepted files</div>
                  <div className="chat-empty__types">
                    {[
                      { ext: "PDF", note: "papers, reports" },
                      { ext: "DOCX", note: "Word documents" },
                      { ext: "TXT / MD", note: "notes, transcripts" },
                      { ext: "PNG / JPG", note: "scans, read by OCR" },
                    ].map((t) => (
                      <span key={t.ext} className="chat-empty__type">
                        <strong>{t.ext}</strong>
                        <span>{t.note}</span>
                      </span>
                    ))}
                  </div>
                  <p className="chat-empty__note">Up to 15 MB per file.</p>
                </>
              )}
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`chat-bubble chat-bubble--${msg.role} liquid-glass`}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
                <span style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--text-muted)" }}>
                  {msg.role === "user" ? "You" : (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
                      <Icon name="spark" size={13} /> Cognita RAG Agent
                    </span>
                  )}
                </span>

                {msg.role === "assistant" && (
                  <button
                    type="button"
                    className={`inspector-toggle-btn ${activeInspectorIndex === i ? "inspector-toggle-btn--open" : ""}`}
                    onClick={() => setActiveInspectorIndex(activeInspectorIndex === i ? null : i)}
                    title="See the sources, retrieval steps and grading behind this answer"
                  >
                    <Icon name="inspector" size={14} />
                    {activeInspectorIndex === i ? "Hide working" : "Show working"}
                    <Icon name="chevron" size={13}
                      style={{ transform: activeInspectorIndex === i ? "rotate(180deg)" : "none", transition: "transform .18s ease" }} />
                  </button>
                )}
              </div>

              <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.65 }}>{msg.content}</div>

              {/* Inline Citation Chips */}
              {msg.sources && msg.sources.length > 0 && (
                <div className="chat-citation-chips">
                  {msg.sources.map((s, j) => (
                    <span key={j} className="citation-chip" title={`Cosine similarity: ${(s.rerank_score ?? s.base_similarity ?? 0).toFixed(2)}`}>
                      <Icon name="sources" size={12} />
                      {s.filename} (Chunk #{s.chunk_index})
                    </span>
                  ))}
                </div>
              )}

              {/* AI Engineering Inspector Panel */}
              {msg.role === "assistant" && activeInspectorIndex === i && (() => {
                const t = msg.telemetry;
                const badge = verdictBadge(t?.llm_judge?.verdict, t?.llm_judge?.available);
                const wasReranked = t?.reranked ?? false;
                return (
                  <div className="engineering-inspector">
                    <div className="inspector-header">
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
                        <Icon name="inspector" size={14} /> How this answer was reached
                      </span>
                      <span className={`judge-badge judge-badge--${badge.tone}`}>{badge.text}</span>
                    </div>

                    {t?.llm_judge?.reasoning && (
                      <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginBottom: "0.6rem", fontStyle: "italic" }}>
                        “{t.llm_judge.reasoning}”
                      </div>
                    )}

                    {/* Judge Metrics Scorecard */}
                    <div className="judge-scorecard">
                      <div className="judge-score">
                        <div className="judge-score__val">{formatPct(t?.faithfulness_score)}</div>
                        <div className="judge-score__lbl">Faithfulness</div>
                      </div>

                      <div className="judge-score">
                        <div className="judge-score__val">{formatPct(t?.answer_relevance)}</div>
                        <div className="judge-score__lbl">Relevance</div>
                      </div>

                      <div className="judge-score">
                        <div className="judge-score__val">{t ? formatPct(t.context_precision) : "—"}</div>
                        <div className="judge-score__lbl">Precision</div>
                      </div>

                      <div className="judge-score">
                        <div className="judge-score__val">{t ? `${t.latency_ms}ms` : "—"}</div>
                        <div className="judge-score__lbl">Latency</div>
                      </div>
                    </div>

                    {/* How the agent actually got here — the interesting part
                        of an agentic loop is the reasoning, not just the result. */}
                    {t?.retrieval_trace && t.retrieval_trace.length > 0 && (
                      <div style={{ marginTop: "0.9rem" }}>
                        <div style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--text-muted)", marginBottom: "0.5rem", display: "flex", alignItems: "center", gap: "0.4rem", flexWrap: "wrap" }}>
                          <Icon name="gap" size={13} />
                          Retrieval reasoning
                          {t.self_corrected && (
                            <span className="chip-selfcorrect">self-corrected</span>
                          )}
                        </div>
                        <ol className="retrieval-trace">
                          {t.retrieval_trace.map((s, k) => (
                            <li key={k} className={`retrieval-trace__item retrieval-trace__item--${s.step}`}>
                              <span className="retrieval-trace__label">{STEP_LABEL[s.step] ?? s.step}</span>
                              {s.query && <span className="retrieval-trace__query">“{s.query}”</span>}
                              <span className="retrieval-trace__meta">
                                {s.found !== undefined && `${s.found} chunk${s.found === 1 ? "" : "s"}`}
                                {s.top_similarity !== undefined && ` · top ${(s.top_similarity * 100).toFixed(0)}%`}
                                {s.verdict && ` · ${s.verdict}`}
                                {s.note}
                              </span>
                            </li>
                          ))}
                        </ol>
                      </div>
                    )}

                    {/* Retrieval Ranking Breakdown */}
                    <div style={{ marginTop: "0.85rem" }}>
                      <div style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--text-muted)", marginBottom: "0.4rem" }}>
                        {wasReranked ? "Cross-Encoder Re-Ranking Telemetry:" : "pgvector Cosine Similarity (no cross-encoder configured):"}
                      </div>
                      <div className="rerank-list">
                        {(t?.reranked_chunks || []).map((chunk, k) => (
                          <div key={k} className="rerank-item">
                            <div style={{ fontSize: "0.75rem", color: "var(--text-primary)" }}>
                              {chunk.filename} (Chunk #{chunk.chunk_index})
                            </div>
                            <div className="rerank-bars">
                              <span style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
                                Base Cosine: {(chunk.base_similarity * 100).toFixed(0)}%
                              </span>
                              {wasReranked && (
                                <span style={{ fontSize: "0.7rem", color: "var(--accent-warm)", fontWeight: 600 }}>
                                  Re-ranked: {(chunk.rerank_score * 100).toFixed(0)}%
                                </span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Execution Trace */}
                    <div className="pipeline-trace">
                      <span>Query Vector (384d)</span> → <span>pgvector Cosine Filter</span>
                      {t?.self_corrected && <> ↺ <span>Rewrite &amp; retry</span></>}
                      {wasReranked && <> → <span>Cohere Cross-Encoder Re-rank</span></>}
                      {t?.model && <> → <span>{t.model} Synthesis</span></>}
                      {" → "}<span>{badge.text}</span>
                    </div>
                  </div>
                );
              })()}
            </div>
          ))}

          {sending && (
            <div className="chat-bubble chat-bubble--assistant liquid-glass">
              <div style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--text-muted)", marginBottom: "0.3rem" }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
                  <Icon name="spark" size={13} /> Cognita RAG Agent
                </span>
              </div>
              <div style={{ color: "var(--text-muted)", fontStyle: "italic" }}>
                Vector retrieval → similarity ranking → LLM-as-a-Judge synthesis...
              </div>
            </div>
          )}
        </div>

        {error && (
          <div className="auth-card__error" style={{ marginBottom: "0.75rem" }}>
            <Icon name="alert" size={15} /> {error}
          </div>
        )}

        {/* Input Bar */}
        <div className="chat-input-bar">
          <input
            type="text"
            placeholder={hasDocuments ? "Ask a grounded question about your uploaded documents…" : "Upload files on the left to ask questions…"}
            value={input}
            maxLength={1000}
            disabled={sending}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
          />
          <button type="button" onClick={send} disabled={sending || !input.trim()}>
            {sending ? "..." : <><Icon name="send" size={15} /> Send</>}
          </button>
        </div>
      </div>
    </div>
  );
}
