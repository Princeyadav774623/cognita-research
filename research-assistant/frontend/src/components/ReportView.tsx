import ReactMarkdown from "react-markdown";
import { useState } from "react";
import type { SessionRecord } from "../api";
import { Icon } from "./Icon";

function confidenceBadgeClass(score: number): string {
  if (score >= 0.8) return "meta-badge--confidence-high";
  if (score >= 0.5) return "meta-badge--confidence-mod";
  return "meta-badge--confidence-low";
}

function confidenceLabel(score: number): string {
  if (score >= 0.8) return "High Grounding";
  if (score >= 0.6) return "Moderate Grounding";
  if (score >= 0.4) return "Low Grounding";
  return "Uncertain";
}

interface Props {
  result: SessionRecord;
}

export function ReportView({ result }: Props) {
  const [copied, setCopied] = useState(false);
  const badgeClass = confidenceBadgeClass(result.confidence);
  const label = confidenceLabel(result.confidence);

  const handleDownloadMarkdown = () => {
    const blob = new Blob([result.final_report], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cognita-research-report-${result.session_id.slice(0, 8)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleCopyReport = async () => {
    try {
      await navigator.clipboard.writeText(result.final_report);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  return (
    <article className="report-paper">
      <header className="report-paper__header">
        <h2 className="report-paper__query-title">{result.query}</h2>

        <div className="report-paper__meta-row">
          <div className="report-paper__badges">
            <span className={`meta-badge ${badgeClass}`}>
              <span>●</span> {label} · {Math.round(result.confidence * 100)}%
            </span>
            <span className="meta-badge meta-badge--sources">
              <Icon name="sources" size={13} /> {result.sources.length} Sources Analyzed
            </span>
            {result.created_at && (
              <span className="meta-badge" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                <Icon name="clock" size={13} /> {new Date(result.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
              </span>
            )}
          </div>

          <div className="report-paper__actions">
            <button type="button" className="paper-action-btn" onClick={handleCopyReport}>
              <Icon name={copied ? "check" : "copy"} size={14} /> {copied ? "Copied" : "Copy Paper"}
            </button>
            <button type="button" className="paper-action-btn" onClick={handleDownloadMarkdown}>
              <Icon name="download" size={14} /> Export Markdown
            </button>
          </div>
        </div>
      </header>

      {result.verified_claims && result.verified_claims.length > 0 && (
        <section className="claims-card">
          <div className="claims-card__title">Verified Claims & Grounding Audit</div>
          <div className="claims-list">
            {result.verified_claims.map((claim, i) => (
              <div key={i} className="claim-item">
                <span className={`claim-item__icon ${claim.verified ? "claim-item__icon--verified" : "claim-item__icon--unverified"}`}>
                  {claim.verified ? "✓" : "✗"}
                </span>
                <span className="claim-item__text">{claim.claim}</span>
                <span className="claim-item__source">
                  ({Math.round(claim.confidence * 100)}% grounded)
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="report-prose">
        <ReactMarkdown>{result.final_report}</ReactMarkdown>
      </div>

      {result.sources && result.sources.length > 0 && (
        <section className="sources-card">
          <div className="sources-card__title">Primary Research References ({result.sources.length})</div>
          <div className="sources-grid">
            {result.sources.map((source, i) => (
              <a
                key={i}
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="source-pill"
              >
                <div className="source-pill__title">{source.title || "Reference Link"}</div>
                <div className="source-pill__url">{source.url}</div>
              </a>
            ))}
          </div>
        </section>
      )}
    </article>
  );
}
