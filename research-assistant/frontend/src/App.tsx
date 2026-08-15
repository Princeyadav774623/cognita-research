import { useEffect, useState } from "react";
import { QueryInput } from "./components/QueryInput";
import { AgentStatusStream } from "./components/AgentStatusStream";
import { ReportView } from "./components/ReportView";
import { HistoryPanel } from "./components/HistoryPanel";
import { AuthScreen } from "./components/AuthScreen";
import { RagSection } from "./RagSection";
import { useResearch } from "./useResearch";
import { useAuth } from "./AuthContext";
import { supabase } from "./supabaseClient";
import type { SessionRecord } from "./api";
import "./App.css";

type Tab = "research" | "rag";

function App() {
  const { session, loading, accessToken } = useAuth();

  if (loading) {
    return <div className="app__splash">Loading…</div>;
  }

  if (!session || !accessToken) {
    return <AuthScreen />;
  }

  return <AuthenticatedApp accessToken={accessToken} userEmail={session.user.email ?? ""} />;
}

function AuthenticatedApp({ accessToken, userEmail }: { accessToken: string; userEmail: string }) {
  const [tab, setTab] = useState<Tab>("research");
  const { phase, steps, result, error, start, reset } = useResearch();
  const [historyKey, setHistoryKey] = useState(0);
  const [viewingHistorical, setViewingHistorical] = useState<SessionRecord | null>(null);

  const handleSubmit = (query: string) => {
    setViewingHistorical(null);
    start(accessToken, query);
  };

  const handleNewSearch = () => {
    reset();
    setViewingHistorical(null);
  };

  const displayedResult = viewingHistorical ?? result;

  useEffect(() => {
    if (phase === "done") setHistoryKey((k) => k + 1);
  }, [phase]);

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__header-row">
          <div>
            <h1>Multi-Agent Research Assistant</h1>
            <p>Five agents — search, read, analyze, fact-check, report — working together on your question.</p>
          </div>
          <div className="app__account">
            <span className="app__account-email">{userEmail}</span>
            <button className="app__signout" onClick={() => supabase.auth.signOut()}>
              Sign out
            </button>
          </div>
        </div>

        <nav className="app__tabs">
          <button
            className={`app__tab ${tab === "research" ? "app__tab--active" : ""}`}
            onClick={() => setTab("research")}
          >
            Research
          </button>
          <button
            className={`app__tab ${tab === "rag" ? "app__tab--active" : ""}`}
            onClick={() => setTab("rag")}
          >
            Chat with Files
          </button>
        </nav>
      </header>

      {tab === "research" && (
        <main className="app__main">
          <section className="app__panel app__panel--primary">
            <QueryInput disabled={phase === "running"} onSubmit={handleSubmit} />

            {phase !== "idle" && (
              <button className="app__reset" onClick={handleNewSearch}>
                ← New search
              </button>
            )}

            {phase === "running" && <AgentStatusStream steps={steps} running />}
            {phase === "error" && <p className="app__error">⚠ {error}</p>}
            {displayedResult && phase !== "running" && <ReportView result={displayedResult} />}
          </section>

          <aside className="app__panel app__panel--sidebar">
            <h3>History</h3>
            <HistoryPanel
              refreshKey={historyKey}
              onSelect={(record) => {
                reset();
                setViewingHistorical(record);
              }}
            />
          </aside>
        </main>
      )}

      {tab === "rag" && <RagSection />}
    </div>
  );
}

export default App;
