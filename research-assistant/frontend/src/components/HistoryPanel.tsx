import { useEffect, useState } from "react";
import { fetchHistory, deleteSession, type SessionRecord } from "../api";
import { useAuth } from "../AuthContext";
import { Icon } from "./Icon";

interface Props {
  refreshKey: number;
  onSelect: (record: SessionRecord) => void;
}

export function HistoryPanel({ refreshKey, onSelect }: Props) {
  const { accessToken } = useAuth();
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!accessToken) return;
    fetchHistory(accessToken)
      .then(setSessions)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load history"));
  }, [refreshKey, accessToken]);

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    if (!accessToken) return;
    try {
      await deleteSession(accessToken, sessionId);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    } catch {
      // Handle error
    }
  };

  return (
    <div className="history-panel">
      <div className="history-panel__header">
        <h3 className="history-panel__title">Research Library</h3>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", color: "var(--text-muted)" }}>
          {sessions.length} Saved
        </span>
      </div>

      {error && <div className="auth-card__error" style={{ fontSize: "0.78rem" }}>{error}</div>}

      {sessions.length === 0 && !error && (
        <div style={{ color: "var(--text-muted)", fontSize: "0.85rem", padding: "1rem 0", textAlign: "center" }}>
          No previous research queries found.
        </div>
      )}

      {sessions.length > 0 && (
        <div className="history-list">
          {sessions.map((session) => (
            // The delete control used to sit inside this button. Nesting a
            // button in a button is invalid HTML — React logs it, the browser
            // silently un-nests it, and keyboard users cannot reach the inner
            // control at all. The row is now a div holding two siblings.
            <div key={session.session_id} className="history-item">
              <button
                type="button"
                className="history-item__open"
                onClick={() => onSelect(session)}
              >
                <div className="history-item__query">{session.query}</div>
                <div className="history-item__meta">
                  <span className="history-item__date">
                    {session.created_at
                      ? new Date(session.created_at).toLocaleDateString(undefined, {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "Recent"}
                  </span>
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      color: session.confidence >= 0.7 ? "var(--success)" : "var(--warning)",
                    }}
                  >
                    {Math.round(session.confidence * 100)}%
                  </span>
                </div>
              </button>
              <button
                type="button"
                className="history-item__delete"
                onClick={(e) => handleDelete(e, session.session_id)}
                aria-label={`Delete research session: ${session.query.slice(0, 60)}`}
                title="Delete session"
              >
                <Icon name="trash" size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
