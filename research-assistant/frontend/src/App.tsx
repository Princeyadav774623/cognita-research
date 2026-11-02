import { useCallback, useEffect, useState } from "react";
import { QueryInput } from "./components/QueryInput";
import { ModeSwitcher } from "./components/ModeSwitcher";
import { AgentStatusStream } from "./components/AgentStatusStream";
import { ReportView } from "./components/ReportView";
import { HistoryPanel } from "./components/HistoryPanel";
import { AuthScreen } from "./components/AuthScreen";
import { MarketingPage } from "./components/MarketingPage";
import { Markdown } from "./components/Markdown";
import { RagSection } from "./RagSection";
import { Icon } from "./components/Icon";
import { useResearch } from "./useResearch";
import { useReveal } from "./useReveal";
import { fetchQuota, startCheckout, type QuotaStatus } from "./billingApi";
import { useAuth } from "./AuthContext";
import { supabase } from "./supabaseClient";
import type { SessionRecord } from "./api";
import "./App.css";

type Tab = "research" | "rag";

function App() {
  const { session, loading, accessToken, recovering, logout } = useAuth();
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    return (localStorage.getItem("cognita_theme") as "dark" | "light") || "dark";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("cognita_theme", theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  };

  if (loading) {
    return (
      <div className="auth-screen">
        <div style={{ textAlign: "center", color: "var(--text-secondary)" }}>
          <div style={{ color: "var(--accent-warm)", marginBottom: "0.5rem", display: "flex", justifyContent: "center" }}>
            <Icon name="spark" size={40} weight={1.4} />
          </div>
          <p style={{ fontFamily: "var(--font-serif)", fontSize: "1.3rem" }}>Initializing Cognita Research...</p>
        </div>
      </div>
    );
  }

  // Checked before the session gate: a recovery link leaves Supabase with a
  // real signed-in session, so gating on `session` alone would drop the
  // visitor straight into the app instead of "choose a new password".
  if (recovering || !session || !accessToken) {
    return <AuthScreen theme={theme} onToggleTheme={toggleTheme} />;
  }

  return (
    <AuthenticatedApp
      accessToken={accessToken}
      userEmail={session.user.email ?? ""}
      theme={theme}
      onToggleTheme={toggleTheme}
      onSignOut={logout}
    />
  );
}

// Must track FREE_QUOTA_PER_MONTH in backend/billing.py — that value is what
// actually gets enforced, and a 402 quoting a different number than the
// pricing card is a support ticket waiting to happen.
const FREE_QUERIES_PER_MONTH = 10;

const FAQS = [
  {
    q: "How does Cognita's 5-Agent Architecture reduce unsupported claims?",
    a: "Unlike single-pass LLMs, Cognita orchestrates an explicit LangGraph state machine. The Planner decomposes queries, the Search and Reader agents fetch external web and paper content, the Analyst synthesizes a preliminary draft, and a dedicated Fact-Checker extracts the draft's key claims and checks each one against the retrieved sources, attaching a per-claim confidence score you can inspect. That catches claims the sources don't support — it is not a guarantee of truth, because a claim can be faithfully drawn from a source that is itself wrong.",
  },
  {
    q: "How does the AI Engineering Inspector (LLM-as-a-Judge & Re-ranking) work in Chat with Files?",
    a: "Every retrieved vector chunk is scored by real pgvector cosine similarity, optionally re-ordered by a Cohere cross-encoder when configured, and synthesized by Groq. A second, independent LLM call then audits the output for Faithfulness and Relevance against the retrieved excerpts and reports a real PASS/PARTIAL/FAIL verdict in the AI Inspector panel — never a hardcoded score.",
  },
  {
    q: "Can I adjust retrieval hyperparameters dynamically?",
    a: "Yes! In 'Chat with Files', open AI Parameter Tuning to adjust Top-K Chunks (1-8), Similarity Threshold, and LLM Temperature to test different epistemic retrieval behaviors.",
  },
  {
    q: "How can I deploy this to Hostinger or custom domains?",
    a: "Cognita's frontend is a standard Vite React single-page application built to dist/ and ready for Hostinger VPS, Cloud, or Static Web Hosting. The FastAPI backend can be containerized on any Linux instance.",
  },
];

/** The hash is the route.
 *
 * Home is the site: hero, the two tools, architecture, benchmarks, pricing and
 * the FAQ. Picking a tool opens it as its own page so there is nothing else on
 * screen while you work, and "Back to home" returns to the full site.
 *
 * Deep links into a marketing section (#pricing) still resolve to home and
 * scroll there, so every link that ever worked still does.
 */
type Route = "home" | "research" | "files";

const TOOL_ROUTES: Record<string, Route> = { research: "research", files: "files" };

function routeFromHash(): Route {
  return TOOL_ROUTES[window.location.hash.replace(/^#/, "")] ?? "home";
}

function AuthenticatedApp({
  accessToken,
  userEmail,
  theme,
  onToggleTheme,
  onSignOut,
}: {
  accessToken: string;
  userEmail: string;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onSignOut?: () => void;
}) {
  const [tab, setTab] = useState<Tab>("research");
  const { phase, steps, result, error, streamedReport, start, resume, reset, stop } = useResearch();
  // A run started before a refresh is still going on the server.
  useEffect(() => { resume(accessToken); }, [resume, accessToken]);
  const [historyKey, setHistoryKey] = useState(0);
  const [viewingHistorical, setViewingHistorical] = useState<SessionRecord | null>(null);
  const [openFaq, setOpenFaq] = useState<number | null>(null);
  const [route, setRoute] = useState<Route>(routeFromHash);

  useEffect(() => {
    const onHashChange = () => {
      const next = routeFromHash();
      setRoute(next);
      if (next !== "home") {
        window.scrollTo({ top: 0, behavior: "instant" });
        return;
      }
      // A marketing anchor lands on home; scroll to the section once it has
      // rendered, since it does not exist until home mounts.
      const anchor = window.location.hash.replace(/^#/, "");
      if (anchor) {
        requestAnimationFrame(() =>
          document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth" })
        );
      }
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const openTool = useCallback((tool: "research" | "files") => {
    window.location.hash = tool;
  }, []);

  const backToHome = useCallback(() => {
    // replaceState rather than a new entry, so the browser's Back button goes
    // where the reader came from instead of toggling between the two.
    history.replaceState(null, "", window.location.pathname + window.location.search);
    setRoute("home");
    window.scrollTo({ top: 0, behavior: "instant" });
  }, []);
  const [quota, setQuota] = useState<QuotaStatus | null>(null);
  const [upgrading, setUpgrading] = useState(false);
  const [billingNote, setBillingNote] = useState<string | null>(null);
  const [stopNotice, setStopNotice] = useState<string | null>(null);

  // Re-observes when the marketing route mounts its own sections.
  useReveal(route);

  // Live plan state, so the pricing card shows what this account actually
  // has left rather than a static marketing number.
  const refreshQuota = useCallback(() => {
    fetchQuota(accessToken).then(setQuota).catch(() => setQuota(null));
  }, [accessToken]);

  useEffect(() => { refreshQuota(); }, [refreshQuota]);

  // Re-check after a completed research run — one query was just spent.
  useEffect(() => { if (phase === "done") refreshQuota(); }, [phase, refreshQuota]);

  const handleUpgrade = async () => {
    setUpgrading(true);
    setBillingNote(null);
    try {
      const result = await startCheckout(accessToken);
      if (result.message) {
        // Server has no Stripe key: the returned URL is a stub that would
        // land on a success page without charging anything. Say so plainly
        // instead of redirecting and implying the upgrade worked.
        setBillingNote("Payments aren't live yet — this deployment has no Stripe key configured.");
        return;
      }
      window.location.href = result.checkout_url;
    } catch (e) {
      setBillingNote(e instanceof Error ? e.message : "Could not start checkout");
    } finally {
      setUpgrading(false);
    }
  };

  const handleSubmit = (query: string) => {
    setViewingHistorical(null);
    setStopNotice(null);
    start(accessToken, query);
  };

  const handleNewSearch = () => {
    reset();
    setViewingHistorical(null);
    setStopNotice(null);
  };

  // Cancelling on the server is what triggers the refund — closing the socket
  // no longer stops anything. Saying so matters: the user is watching a
  // counter they only get ten of a month.
  const handleStop = async () => {
    setViewingHistorical(null);
    try {
      await stop(accessToken);
      setStopNotice("Research stopped. That query has been returned to your monthly allowance.");
    } catch {
      setStopNotice("Couldn't reach the server to stop the research — it may still finish and appear in your history.");
    }
    refreshQuota();
  };

  const displayedResult = viewingHistorical ?? result;

  useEffect(() => {
    if (phase === "done") setHistoryKey((k) => k + 1);
  }, [phase]);

  return (
    <div className="app">
      {/* Sticky Header & Anthropic / Apple Navigation */}
      <header className="app__header">
        <div className="app__header-top">
          <a
            href="#top"
            className="app__brand"
            onClick={(e) => {
              e.preventDefault();
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
          >
            <span className="app__brand-logo"><Icon name="spark" size={22} weight={1.6} /></span>
            <div className="app__brand-title">
              Cognita <span style={{ fontWeight: 300, color: "var(--text-secondary)" }}>Research</span>
              <span className="app__brand-badge">5-Agent System</span>
            </div>
          </a>

          <nav className="app__nav-links">
            {/* Section links only. "Research" / "Chat with Files" used to sit
                here too, duplicating the tab row directly below with different
                labels and different scroll behaviour. */}
            <a href="#architecture" className="app__nav-link">
              Architecture
            </a>
            <a href="#benchmarks" className="app__nav-link">
              Benchmarks
            </a>
            <a href="#pricing" className="app__nav-link">
              Pricing
            </a>
            <a href="#faq" className="app__nav-link">
              FAQ
            </a>
          </nav>

          <div className="app__header-actions">
            <button
              type="button"
              className="app__theme-toggle"
              onClick={onToggleTheme}
              title={`Switch to ${theme === "dark" ? "Light" : "Dark"} mode`}
              aria-label="Toggle theme"
            >
              <Icon name={theme === "dark" ? "sun" : "moon"} size={17} />
            </button>

            <div className="app__account-pill">
              <div className="app__account-avatar">
                {userEmail ? userEmail[0].toUpperCase() : "U"}
              </div>
              <span className="app__account-email" title={userEmail}>
                {userEmail}
              </span>
              <button
                type="button"
                className="app__signout-btn"
                onClick={() => (onSignOut ? onSignOut() : supabase.auth.signOut())}
                title="Sign out of your account"
              >
                Sign out
              </button>
            </div>
          </div>
        </div>

      </header>

      {route === "home" && (
        <>
          <section className="hero">
            <h1 className="hero__headline">
              Research that shows <em>its working</em>.
            </h1>
            <p className="hero__description">
              Five agents search, read, and check every claim against its source.
            </p>

            {/* No data-reveal: this is above the fold, so gating it on a
                scroll observer leaves the page's main visual blank at rest. */}
            <figure className="hero__plate" data-revealed="true">
              <img
                src={theme === "dark" ? "/visual-network-dark.png" : "/visual-network.png"}
                alt="Ink diagram of connected research nodes tracing overlapping orbital paths"
                loading="eager"
                width={1376}
                height={768}
              />
            </figure>
          </section>

          {/* The two tools, as the way into the app. */}
          <section className="tools-section" id="tools">
            <ModeSwitcher mode={tab} onChange={(m) => { setTab(m); openTool(m === "rag" ? "files" : "research"); }} asEntry />
          </section>

          <MarketingPage
            theme={theme}
            quota={quota}
            upgrading={upgrading}
            billingNote={billingNote}
            openFaq={openFaq}
            onToggleFaq={setOpenFaq}
            onUpgrade={handleUpgrade}
            onBackToApp={backToHome}
            freeQueriesPerMonth={FREE_QUERIES_PER_MONTH}
            faqs={FAQS}
          />
        </>
      )}

      {/* Each tool is its own page: nothing else on screen while you work. */}
      {route !== "home" && <section id="workspace" style={{ minHeight: "650px", marginBottom: "4rem" }}>
        <button type="button" className="marketing-back" onClick={backToHome}>
          <Icon name="chevron" size={15} style={{ transform: "rotate(90deg)" }} /> Back to home
        </button>

        <div className={`app__main-grid ${route === "files" ? "app__main-grid--full" : ""}`}>
          <main className="app__content-column">
            {route === "research" && (
              <>
                {/* The tool page opened straight onto an input box with nothing
                    naming it. This mirrors the Files page header, and brings
                    back the spaced mono eyebrow the old hero used. */}
                <header className="tool-header">
                  <div className="tool-header__eyebrow">
                    <Icon name="spark" size={12} /> Autonomous Epistemic Intelligence
                  </div>
                  <h2 className="tool-header__title">
                    Ask it, and <em>watch it work</em>.
                  </h2>
                  <p className="tool-header__subtitle">
                    Five agents plan the question, search the web, read the sources, and
                    check every claim before answering.
                  </p>
                </header>

                <QueryInput disabled={phase === "running"} onSubmit={handleSubmit} />
              </>
            )}

            {route === "files" && <RagSection />}

            {route === "research" && (
              <>

              {phase === "running" && (
                <button type="button" className="new-search-btn new-search-btn--stop" onClick={handleStop}>
                  <Icon name="alert" size={15} /> Stop research
                </button>
              )}
              {phase !== "idle" && phase !== "running" && (
                <button type="button" className="new-search-btn" onClick={handleNewSearch}>
                  <Icon name="chevron" size={15} style={{ transform: "rotate(90deg)" }} /> New research query
                </button>
              )}
              {stopNotice && <div className="stop-notice">{stopNotice}</div>}

              {phase === "running" && <AgentStatusStream steps={steps} running />}

              {/* The report as it is written. Time-to-first-token is what the
                  reader actually experiences — waiting on a spinner for two
                  minutes and watching text arrive are very different products,
                  even at identical total latency. */}
              {phase === "running" && streamedReport && (
                <article className="report-paper streaming-report" data-reveal data-revealed="true">
                  <div className="streaming-report__badge">
                    <span className="agent-stream__pulse" />
                    Writing the report…
                  </div>
                  <div className="report-prose">
                    <Markdown>{streamedReport}</Markdown>
                  </div>
                </article>
              )}
              {phase === "error" && (
                <div style={{ marginBottom: "1.5rem" }}>
                  <div className="auth-card__error">
                    <Icon name="alert" size={15} /> {error}
                  </div>
                  {/* Running out of quota is the highest-intent moment in the
                      product. Offer the upgrade right here rather than leaving
                      the user at a dead-end error and hoping they scroll to
                      the pricing section. */}
                  {error?.toLowerCase().includes("quota") && (
                    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginTop: "0.85rem", flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="pricing-card__btn pricing-card__btn--primary"
                        style={{ width: "auto", padding: "0.55rem 1.25rem" }}
                        onClick={handleUpgrade}
                        disabled={upgrading}
                      >
                        {upgrading ? "Starting checkout…" : "Upgrade to Pro"}
                      </button>
                      <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
                        Your monthly queries reset at the start of next month.
                      </span>
                    </div>
                  )}
                  {billingNote && (
                    <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.6rem" }}>{billingNote}</p>
                  )}
                </div>
              )}
              {displayedResult && phase !== "running" && <ReportView result={displayedResult} />}
              </>
            )}
          </main>

          {/* Research history only. On the Files page it was a fourth column
              of unrelated content squeezing the chat, so it renders only where
              it means something. */}
          {route === "research" && (
            <aside className="app__sidebar-column">
              <HistoryPanel
                refreshKey={historyKey}
                onSelect={(record) => {
                  reset();
                  setViewingHistorical(record);
                }}
              />
            </aside>
          )}

        </div>
      </section>}

      {/* Full-bleed showcase band — an Apple-style change of scale between
          reading sections, and the plate's five columns echo the five agents. */}

      {/* Marketing lives on its own route now — see components/MarketingPage. */}

            <footer className="app-footer">
        <div className="app-footer__grid">
          <div>
            <div className="app__brand-title" style={{ marginBottom: "0.5rem" }}>
              <span className="app__brand-logo"><Icon name="spark" size={22} weight={1.6} /></span> Cognita Research
            </div>
            <p className="app-footer__brand-p">
              Autonomous multi-agent research platform powered by LangGraph, Groq, and Tavily. Built for intellectual rigor and verified truth.
            </p>
          </div>

          <div>
            <div className="app-footer__col-title">Platform</div>
            <ul className="app-footer__links">
              <li><a href="#top" className="app-footer__link" onClick={(e) => { e.preventDefault(); setTab("research"); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Deep Research</a></li>
              <li><a href="#top" className="app-footer__link" onClick={(e) => { e.preventDefault(); setTab("rag"); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Chat with Files</a></li>
              <li><a href="#architecture" className="app-footer__link">5-Agent Graph</a></li>
              <li><a href="#benchmarks" className="app-footer__link">Grounding Benchmarks</a></li>
            </ul>
          </div>

          <div>
            <div className="app-footer__col-title">Resources</div>
            <ul className="app-footer__links">
              <li><a href="#faq" className="app-footer__link">Documentation & FAQ</a></li>
              <li><a href="#pricing" className="app-footer__link">Pricing Tiers</a></li>
              <li><a href="https://hostinger.com" target="_blank" rel="noopener noreferrer" className="app-footer__link">Hostinger Deployment</a></li>
            </ul>
          </div>

          <div>
            <div className="app-footer__col-title">Security & Tech</div>
            <ul className="app-footer__links">
              <li><span className="app-footer__link u-muted">Supabase JWT Auth</span></li>
              <li><span className="app-footer__link u-muted">Postgres Row Security</span></li>
              <li><span className="app-footer__link u-muted">GDPR Session Purge</span></li>
            </ul>
          </div>
        </div>

        <div className="app-footer__bottom">
          <div>
            © {new Date().getFullYear()} Cognita Research Platform. All rights reserved.
          </div>
          <div className="app-footer__status">
            <span className="status-beacon" />
            <span>All 5 Research Agents Operational</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default App;
