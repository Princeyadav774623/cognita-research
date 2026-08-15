import { useRef, useState, useEffect } from "react";
import { sendChatMessage, type ChatMessage } from "../ragApi";
import { useAuth } from "../AuthContext";

interface Props {
  hasDocuments: boolean;
}

export function ChatPanel({ hasDocuments }: Props) {
  const { accessToken } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    const message = input.trim();
    if (!message || sending || !accessToken) return;

    setMessages((prev) => [...prev, { role: "user", content: message, sources: [] }]);
    setInput("");
    setSending(true);
    setError(null);

    try {
      const res = await sendChatMessage(accessToken, message, conversationId);
      setConversationId(res.conversation_id);
      setMessages((prev) => [...prev, { role: "assistant", content: res.answer, sources: res.sources }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to send message");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="chat-panel">
      <div className="chat-panel__messages">
        {messages.length === 0 && (
          <p className="chat-panel__placeholder">
            {hasDocuments
              ? "Ask a question about your uploaded documents."
              : "Upload a document first, then ask questions about it here."}
          </p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`chat-msg chat-msg--${msg.role}`}>
            <div className="chat-msg__bubble">{msg.content}</div>
            {msg.sources.length > 0 && (
              <div className="chat-msg__sources">
                {msg.sources.map((s, j) => (
                  <span key={j} className="chat-msg__source-chip">
                    {s.filename}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {sending && (
          <div className="chat-msg chat-msg--assistant">
            <div className="chat-msg__bubble chat-msg__bubble--typing">…</div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {error && <p className="chat-panel__error">⚠ {error}</p>}

      <div className="chat-panel__input-row">
        <input
          type="text"
          placeholder="Ask about your documents…"
          value={input}
          maxLength={1000}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button onClick={send} disabled={sending || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
