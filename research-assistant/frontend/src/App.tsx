import { useCallback, useEffect, useState } from "react";
import { QueryInput } from "./components/QueryInput";
import { AgentStatusStream } from "./components/AgentStatusStream";
import { ReportView } from "./components/ReportView";
import { HistoryPanel } from "./components/HistoryPanel";
import { AuthScreen } from "./components/AuthScreen";
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
  const { phase, steps, result, error, streamedReport, start, reset } = useResearch();
  const [historyKey, setHistoryKey] = useState(0);
  const [viewingHistorical, setViewingHistorical] = useState<SessionRecord | null>(null);
  const [openFaq, setOpenFaq] = useState<number | null>(null);
  const [quota, setQuota] = useState<QuotaStatus | null>(null);
  const [upgrading, setUpgrading] = useState(false);
  const [billingNote, setBillingNote] = useState<string | null>(null);
  const [stopNotice, setStopNotice] = useState<string | null>(null);

  useReveal();

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

  // Closing the socket is what triggers the refund: the server treats a
  // disconnect before the report was saved exactly like a failed run and hands
  // the reserved query back. Saying so matters — the user is watching a
  // counter they only get ten of a month.
  const handleStop = () => {
    reset();
    setViewingHistorical(null);
    setStopNotice("Research stopped. That query has been returned to your monthly allowance.");
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

        <nav className="app__tabs">
          <button
            type="button"
            className={`app__tab ${tab === "research" ? "app__tab--active" : ""}`}
            onClick={() => {
              setTab("research");
              window.scrollTo({ top: 0, behavior: "instant" });
            }}
          >
            {tab === "research" && <span className="app__tab-dot" />}
            Deep Research
          </button>
          <button
            type="button"
            className={`app__tab ${tab === "rag" ? "app__tab--active" : ""}`}
            onClick={() => {
              setTab("rag");
              window.scrollTo({ top: 0, behavior: "instant" });
            }}
          >
            {tab === "rag" && <span className="app__tab-dot" />}
            Chat with Files
          </button>
        </nav>
      </header>

      {/* Hero Header Section - Only on Research Tab */}
      {tab === "research" && phase === "idle" && !displayedResult && (
        <section className="hero">
          <div className="hero__eyebrow">
            <Icon name="spark" size={13} /> Autonomous Epistemic Intelligence
          </div>
          <h1 className="hero__headline">
            Frontier multi-agent research, powered by <em>collaborative reasoning</em>.
          </h1>
          <p className="hero__description">
            Five specialized agents—Planner, Web Search, Document Reader, Synthesis Analyst, and Strict Fact-Checker—collaborate in a recursive loop to produce verified, citation-backed research papers.
          </p>

          <figure className="hero__plate" data-reveal data-reveal-delay="120">
            <img
              src={theme === "dark" ? "/visual-network-dark.png" : "/visual-network.png"}
              alt="Fine ink diagram of connected research nodes tracing overlapping orbital paths"
              loading="eager"
              width={1376}
              height={768}
            />
          </figure>
        </section>
      )}

      {/* Main Interactive Research Workspace */}
      <section id="workspace" style={{ minHeight: "650px", marginBottom: "4rem" }}>
        {tab === "research" && (
          <div className="app__main-grid">
            <main className="app__content-column">
              <QueryInput disabled={phase === "running"} onSubmit={handleSubmit} />

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
            </main>

            <aside className="app__sidebar-column">
              <HistoryPanel
                refreshKey={historyKey}
                onSelect={(record) => {
                  reset();
                  setViewingHistorical(record);
                }}
              />
            </aside>
          </div>
        )}

        {tab === "rag" && <RagSection />}
      </section>

      {/* Full-bleed showcase band — an Apple-style change of scale between
          reading sections, and the plate's five columns echo the five agents. */}
      <section className="bleed showcase" data-reveal>
        <div className="showcase__eyebrow">The pipeline</div>
        <h2 className="showcase__title">Every claim traced back to its source.</h2>
        <p className="showcase__sub">
          Five agents hand work to one another in a recursive loop — planning, gathering,
          reading, synthesising, and verifying — so each statement in the final paper
          carries the evidence it came from.
        </p>
        <figure className="media-frame" style={{ margin: "0 auto" }}>
          <img
            src={theme === "dark" ? "/visual-pipeline-dark.png" : "/visual-pipeline.png"}
            alt="Ink plate of five connected columns representing the five research agents and the evidence passed between them"
            loading="lazy"
            width={1376}
            height={768}
          />
        </figure>
      </section>

      {/* Section 1: Architecture Showcase */}
      <section id="architecture" className="website-section">
        <div className="section-header" data-reveal>
          <div className="section-header__eyebrow">LangGraph Architecture</div>
          <h2 className="section-header__title">Five Collaborative Autonomous Agents</h2>
          <p className="section-header__subtitle">
            Cognita replaces brittle single-prompt calls with a structured multi-agent graph with self-reflection, evidence gathering, and claim-level verification.
          </p>
        </div>

        <div className="architecture-grid">
          <div className="arch-card" data-reveal data-reveal-delay="0">
            <div className="arch-card__icon"><Icon name="compass" size={26} /></div>
            <div className="arch-card__name">Planner Agent</div>
            <div className="arch-card__role">Query Decomposition</div>
            <div className="arch-card__desc">
              Analyzes complex inquiries, detects conceptual dependencies, and generates targeted search vectors.
            </div>
            <span className="arch-card__badge">Deterministic JSON</span>
          </div>

          <div className="arch-card" data-reveal data-reveal-delay="90">
            <div className="arch-card__icon"><Icon name="search" size={26} /></div>
            <div className="arch-card__name">Search Agent</div>
            <div className="arch-card__role">Live Web Gathering</div>
            <div className="arch-card__desc">
              Executes parallel search queries via Tavily API to gather up to 40 academic and industry sources.
            </div>
            <span className="arch-card__badge">Multi-Source</span>
          </div>

          <div className="arch-card" data-reveal data-reveal-delay="180">
            <div className="arch-card__icon"><Icon name="document" size={26} /></div>
            <div className="arch-card__name">Reader Agent</div>
            <div className="arch-card__role">Document Extraction</div>
            <div className="arch-card__desc">
              Parses HTML, PDF, and Markdown content with resilient fallback to search snippet vectors on 403 blocks.
            </div>
            <span className="arch-card__badge">Async Scraping</span>
          </div>

          <div className="arch-card" data-reveal data-reveal-delay="270">
            <div className="arch-card__icon"><Icon name="brain" size={26} /></div>
            <div className="arch-card__name">Analyst Agent</div>
            <div className="arch-card__role">Epistemic Synthesis</div>
            <div className="arch-card__desc">
              Synthesizes insights across dozens of documents, identifying consensus, controversies, and key data points.
            </div>
            <span className="arch-card__badge">Cross-Document</span>
          </div>

          <div className="arch-card" data-reveal data-reveal-delay="360">
            <div className="arch-card__icon"><Icon name="verified" size={26} /></div>
            <div className="arch-card__name">Fact-Checker</div>
            <div className="arch-card__role">Claim Verification</div>
            <div className="arch-card__desc">
              Extracts factual claims and verifies each claim against retrieved sources, assigning grounded confidence scores.
            </div>
            <span className="arch-card__badge">Zero Tolerance</span>
          </div>
        </div>
      </section>

      {/* Section 2: Benchmarks & Telemetry */}
      <section id="benchmarks" className="website-section">
        <div className="section-header" data-reveal>
          <div className="section-header__eyebrow">Measured, not claimed</div>
          <h2 className="section-header__title">What the evaluation set actually shows</h2>
          <p className="section-header__subtitle">
            Every figure below comes from a suite you can re-run yourself: <code>python -m evals.run --answers</code> in
            the backend. The golden set is deliberately small — 14 questions over 3 synthetic documents, 5 of them
            unanswerable on purpose — so treat these as a regression check, not a public benchmark.
          </p>
        </div>

        <div className="benchmarks-grid">
          <div className="stat-card" data-reveal data-reveal-delay="0">
            <div className="stat-card__number">9/9</div>
            <div className="stat-card__label">Answerable questions retrieved</div>
            <div className="stat-card__subtext">Each one reached the source document it had to be answered from</div>
          </div>

          <div className="stat-card" data-reveal data-reveal-delay="80">
            <div className="stat-card__number">5/5</div>
            <div className="stat-card__label">Unanswerable questions declined</div>
            <div className="stat-card__subtext">Refused rather than answered from the model's own parametric knowledge</div>
          </div>

          <div className="stat-card" data-reveal data-reveal-delay="160">
            <div className="stat-card__number">2.7×</div>
            <div className="stat-card__label">Faster Synthesis</div>
            <div className="stat-card__subtext">361s to 134s end-to-end on an instrumented benchmark run</div>
          </div>

          <div className="stat-card" data-reveal data-reveal-delay="240">
            <div className="stat-card__number">89</div>
            <div className="stat-card__label">Automated Tests</div>
            <div className="stat-card__subtext">Unit-level and run on every push, alongside the golden set above</div>
          </div>
        </div>
      </section>

      {/* Section 3: Pricing & Access */}
      <section id="pricing" className="website-section">
        <div className="section-header" data-reveal>
          <div className="section-header__eyebrow">Transparent Plans</div>
          <h2 className="section-header__title">Designed for Researchers & Teams</h2>
          <p className="section-header__subtitle">
            Start free with autonomous research queries or upgrade for unlimited synthesis and API access.
          </p>
        </div>

        <div className="pricing-grid">
          <div className="pricing-card">
            <div className="pricing-card__name">Explorer</div>
            <div className="pricing-card__desc">Ideal for students and individual research tasks.</div>
            <div className="pricing-card__price">
              $0 <span>/ month</span>
            </div>
            <ul className="pricing-features">
              <li className="pricing-feature"><span className="pricing-feature__icon"><Icon name="check" size={14} weight={2} /></span>
                {quota && quota.plan_tier === "free"
                  ? `${quota.remaining_queries} of ${quota.quota_limit} Deep Research queries left this month`
                  : `${FREE_QUERIES_PER_MONTH} Deep Research queries / mo`}
              </li>
              <li className="pricing-feature"><span className="pricing-feature__icon"><Icon name="check" size={14} weight={2} /></span> 5-Agent LangGraph pipeline</li>
              <li className="pricing-feature"><span className="pricing-feature__icon"><Icon name="check" size={14} weight={2} /></span> Markdown report export</li>
              <li className="pricing-feature"><span className="pricing-feature__icon"><Icon name="check" size={14} weight={2} /></span> Document uploads up to 15MB each</li>
            </ul>
            <button type="button" className="pricing-card__btn" onClick={() => setTab("research")}>
              {quota?.plan_tier === "pro" ? "Free plan" : "Current plan"}
            </button>
          </div>

          <div className="pricing-card pricing-card--popular">
            <span className="pricing-card__pill">Recommended</span>
            <div className="pricing-card__name">Pro Researcher</div>
            <div className="pricing-card__desc">For analysts, scientists, and power researchers.</div>
            <div className="pricing-card__price">
              $20 <span>/ month</span>
            </div>
            <ul className="pricing-features">
              <li className="pricing-feature"><span className="pricing-feature__icon"><Icon name="check" size={14} weight={2} /></span> Unlimited Deep Research queries</li>
              <li className="pricing-feature"><span className="pricing-feature__icon"><Icon name="check" size={14} weight={2} /></span> Unlimited PDF / document RAG</li>
              <li className="pricing-feature"><span className="pricing-feature__icon"><Icon name="check" size={14} weight={2} /></span> Verified Claim Audit Trail</li>
              <li className="pricing-feature"><span className="pricing-feature__icon"><Icon name="check" size={14} weight={2} /></span> LLM-as-a-Judge Telemetry</li>
            </ul>
            <button
              type="button"
              className="pricing-card__btn pricing-card__btn--primary"
              onClick={handleUpgrade}
              disabled={upgrading || quota?.plan_tier === "pro"}
            >
              {quota?.plan_tier === "pro"
                ? "Current plan"
                : upgrading
                  ? "Starting checkout…"
                  : "Upgrade to Pro"}
            </button>
            {billingNote && (
              <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.75rem", lineHeight: 1.45 }}>
                {billingNote}
              </p>
            )}
          </div>

          <div className="pricing-card">
            <div className="pricing-card__name">Enterprise & Lab</div>
            <div className="pricing-card__desc">Custom deployments for organizations and labs.</div>
            <div className="pricing-card__price">
              Custom <span>/ team</span>
            </div>
            <ul className="pricing-features">
              <li className="pricing-feature"><span className="pricing-feature__icon"><Icon name="check" size={14} weight={2} /></span> Dedicated self-hosted VPS / Hostinger</li>
              <li className="pricing-feature"><span className="pricing-feature__icon"><Icon name="check" size={14} weight={2} /></span> Private Supabase & PostgreSQL instance</li>
              <li className="pricing-feature"><span className="pricing-feature__icon"><Icon name="check" size={14} weight={2} /></span> Custom agent graph customization</li>
              <li className="pricing-feature"><span className="pricing-feature__icon"><Icon name="check" size={14} weight={2} /></span> 24/7 SLA & Team onboarding</li>
            </ul>
            <button type="button" className="pricing-card__btn">
              Contact Enterprise
            </button>
          </div>
        </div>
      </section>

      {/* Section 4: FAQ Accordion */}
      <section id="faq" className="website-section">
        <div className="section-header" data-reveal>
          <div className="section-header__eyebrow">Common Questions</div>
          <h2 className="section-header__title">Frequently Asked Questions</h2>
          <p className="section-header__subtitle">
            Everything you need to know about Cognita's architecture and capabilities.
          </p>
        </div>

        <div className="faq-grid">
          {FAQS.map((faq, i) => {
            const isOpen = openFaq === i;
            return (
              <div
                key={i}
                className="faq-item"
                onClick={() => setOpenFaq(isOpen ? null : i)}
              >
                <div className="faq-item__question">
                  <span>{faq.q}</span>
                  <span className="faq-item__toggle">{isOpen ? "−" : "+"}</span>
                </div>
                {isOpen && <div className="faq-item__answer">{faq.a}</div>}
              </div>
            );
          })}
        </div>
      </section>

      {/* Editorial Footer */}
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
              <li><span className="app-footer__link" style={{ color: "var(--text-muted)" }}>Supabase JWT Auth</span></li>
              <li><span className="app-footer__link" style={{ color: "var(--text-muted)" }}>Postgres Row Security</span></li>
              <li><span className="app-footer__link" style={{ color: "var(--text-muted)" }}>GDPR Session Purge</span></li>
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
