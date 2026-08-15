import { useEffect, useState } from "react";
import { fetchHistory, deleteSession, type SessionRecord } from "../api";
import { useAuth } from "../AuthContext";

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
    await deleteSession(accessToken, sessionId);
    setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
  };

  if (error) return <p className="history-panel__error">{error}</p>;
  if (sessions.length === 0) return <p className="history-panel__empty">No past research yet.</p>;

  return (
    <ul className="history-panel">
      {sessions.map((session) => (
        <li key={session.session_id} className="history-panel__item" onClick={() => onSelect(session)}>
          <div className="history-panel__query">{session.query}</div>
          <div className="history-panel__meta">
            <span>{new Date(session.created_at).toLocaleString()}</span>
            <span>{Math.round(session.confidence * 100)}%</span>
            <button className="history-panel__delete" onClick={(e) => handleDelete(e, session.session_id)}>
              Delete
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}
