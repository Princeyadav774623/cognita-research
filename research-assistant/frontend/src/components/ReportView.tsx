import { Markdown } from "./Markdown";
import { useCallback, useRef, useState } from "react";
import type { SessionRecord } from "../api";
import { confidenceBand } from "../confidence";
import { toBibTeX, downloadText } from "../exportReport";
import { Icon } from "./Icon";

interface Props {
  result: SessionRecord;
}

/** Sources are addressed by index so a claim can point at one. */
function sourceDomId(sessionId: string, index: number) {
  return `source-${sessionId}-${index}`;
}

/** Match a claim's cited source string against the run's source list.
 *  The verifier returns whatever it judged by — a title, a URL, or a bare
 *  domain — so all three have to resolve. */
function findSourceIndex(citation: string, sources: { title: string; url: string }[]): number {
  if (!citation) return -1;
  const needle = citation.trim().toLowerCase();
  if (!needle || needle === "unknown") return -1;

  const exact = sources.findIndex(
    (s) => s.url.toLowerCase() === needle || s.title.toLowerCase() === needle
  );
  if (exact !== -1) return exact;

  return sources.findIndex((s) => {
    const url = s.url.toLowerCase();
    const title = s.title.toLowerCase();
    return url.includes(needle) || needle.includes(url) ||
           title.includes(needle) || needle.includes(title);
  });
}

export function ReportView({ result }: Props) {
  const [copied, setCopied] = useState(false);
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const band = confidenceBand(result.confidence);
  const sources = result.sources ?? [];
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // The architecture exists to make claims traceable; until now the audit and
  // the source list sat in the same report with nothing joining them.
  const revealSource = useCallback((index: number) => {
    const el = document.getElementById(sourceDomId(result.session_id, index));
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlighted(index);
    if (highlightTimer.current) clearTimeout(highlightTimer.current);
    highlightTimer.current = setTimeout(() => setHighlighted(null), 2400);
  }, [result.session_id]);

  const slug = result.session_id.slice(0, 8);

  const handleDownloadMarkdown = () =>
    downloadText(`cognita-report-${slug}.md`, result.final_report, "text/markdown");

  const handleDownloadBibTeX = () =>
    downloadText(`cognita-sources-${slug}.bib`, toBibTeX(result), "application/x-bibtex");

  // The browser's own print engine rather than a PDF library: it hyphenates,
  // breaks pages and embeds fonts better than anything worth bundling, and the
  // print stylesheet already strips the app chrome.
  const handlePrint = () => window.print();

  const handleCopyReport = async () => {
    try {
      await navigator.clipboard.writeText(result.final_report);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard permission denied — the Export button still works.
    }
  };

  return (
    <article className="report-paper">
      <header className="report-paper__header">
        <h2 className="report-paper__query-title">{result.query}</h2>

        <div className="report-paper__meta-row">
          <div className="report-paper__badges">
            <span className={`meta-badge meta-badge--confidence-${band.tone}`}>
              <span>●</span> {band.label} · {Math.round(result.confidence * 100)}%
            </span>
            <span className="meta-badge meta-badge--sources">
              <Icon name="sources" size={13} /> {sources.length} sources analysed
            </span>
            {result.created_at && (
              <span className="meta-badge" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                <Icon name="clock" size={13} /> {new Date(result.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
              </span>
            )}
          </div>

          <div className="report-paper__actions">
            <button type="button" className="paper-action-btn" onClick={handleCopyReport}>
              <Icon name={copied ? "check" : "copy"} size={14} /> {copied ? "Copied" : "Copy"}
            </button>
            <button type="button" className="paper-action-btn" onClick={handleDownloadMarkdown}>
              <Icon name="download" size={14} /> Markdown
            </button>
            <button type="button" className="paper-action-btn" onClick={handleDownloadBibTeX}>
              <Icon name="sources" size={14} /> BibTeX
            </button>
            <button type="button" className="paper-action-btn" onClick={handlePrint}>
              <Icon name="report" size={14} /> PDF
            </button>
          </div>
        </div>
      </header>

      {result.verified_claims && result.verified_claims.length > 0 && (
        <section className="claims-card">
          <div className="claims-card__title">Verified claims &amp; grounding audit</div>
          <div className="claims-list">
            {result.verified_claims.map((claim, i) => {
              const sourceIndex = findSourceIndex(claim.source, sources);
              const linkable = sourceIndex !== -1;
              return (
                <div key={i} className="claim-item">
                  <span className={`claim-item__icon ${claim.verified ? "claim-item__icon--verified" : "claim-item__icon--unverified"}`}>
                    {claim.verified ? "✓" : "✗"}
                  </span>
                  <span className="claim-item__text">{claim.claim}</span>
                  {linkable ? (
                    <button
                      type="button"
                      className="claim-item__source claim-item__source--link"
                      onClick={() => revealSource(sourceIndex)}
                      title={`Show the source this was checked against: ${sources[sourceIndex].title}`}
                    >
                      {Math.round(claim.confidence * 100)}% grounded ·{" "}
                      <span className="claim-item__jump">see source</span>
                    </button>
                  ) : (
                    <span className="claim-item__source">
                      {Math.round(claim.confidence * 100)}% grounded
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      <div className="report-prose">
        <Markdown>{result.final_report}</Markdown>
      </div>

      {(result.images ?? []).length > 0 && (
        <section className="figures-card">
          <div className="figures-card__title">
            Figures from the sources ({(result.images ?? []).length})
          </div>
          <div className="figures-grid">
            {(result.images ?? []).slice(0, 8).map((img, i) => (
              <a
                key={i}
                href={img.url}
                target="_blank"
                rel="noopener noreferrer"
                className="figure-tile"
              >
                <img
                  src={img.url}
                  alt={img.description || "Figure from a cited source"}
                  loading="lazy"
                  // A dead image URL leaves an empty frame with no explanation,
                  // so the tile removes itself instead.
                  onError={(e) => {
                    const tile = (e.target as HTMLElement).closest(".figure-tile");
                    if (tile) (tile as HTMLElement).style.display = "none";
                  }}
                />
                {img.description && (
                  <div className="figure-tile__caption">{img.description}</div>
                )}
              </a>
            ))}
          </div>
        </section>
      )}

      {sources.length > 0 && (
        <section className="sources-card">
          <div className="sources-card__title">Primary research references ({sources.length})</div>
          <div className="sources-grid">
            {sources.map((source, i) => (
              <a
                key={i}
                id={sourceDomId(result.session_id, i)}
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="source-pill"
                // Set inline rather than via a modifier class: .source-pill is
                // defined later in App.css than any modifier could be appended,
                // so a class-based highlight lost the cascade and silently did
                // nothing. An inline style is not in that contest.
                style={
                  highlighted === i
                    ? {
                        borderColor: "var(--accent-warm)",
                        boxShadow: "0 0 0 3px var(--accent-subtle)",
                      }
                    : undefined
                }
              >
                <div className="source-pill__title">{source.title || "Reference link"}</div>
                <div className="source-pill__url">{source.url}</div>
              </a>
            ))}
          </div>
        </section>
      )}
    </article>
  );
}
