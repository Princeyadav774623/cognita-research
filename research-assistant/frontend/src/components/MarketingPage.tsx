import { Icon } from "./Icon";
import type { QuotaStatus } from "../billingApi";

/**
 * The marketing page: what Cognita is, how it works, what it costs.
 *
 * This used to render underneath the workspace on every page load, so a
 * signed-in user scrolled past a hero, an architecture tour, benchmarks and a
 * pricing table to reach the thing they came to use — the conversion surface
 * and the working surface were the same page, and the app was ~8,300px tall
 * before anyone had asked a question.
 *
 * It now lives behind the header's own links. The anchors that used to scroll
 * within one page still work as deep links, because the route is the hash.
 */

export const MARKETING_ROUTES = ["architecture", "benchmarks", "pricing", "faq"] as const;
export type MarketingRoute = (typeof MARKETING_ROUTES)[number];

interface Props {
  theme: "dark" | "light";
  quota: QuotaStatus | null;
  upgrading: boolean;
  billingNote: string | null;
  openFaq: number | null;
  onToggleFaq: (index: number | null) => void;
  onUpgrade: () => void;
  /** Kept so the pricing card's "current plan" button can return home. */
  onBackToApp: () => void;
  freeQueriesPerMonth: number;
  faqs: { q: string; a: string }[];
}

export function MarketingPage({
  theme,
  quota,
  upgrading,
  billingNote,
  openFaq,
  onToggleFaq,
  onUpgrade,
  onBackToApp,
  freeQueriesPerMonth: FREE_QUERIES_PER_MONTH,
  faqs: FAQS,
}: Props) {
  const setOpenFaq = (v: number | null) => onToggleFaq(v);
  const handleUpgrade = onUpgrade;
  const setTab = (_: string) => onBackToApp();

  return (
    <>
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
    </>
  );
}
