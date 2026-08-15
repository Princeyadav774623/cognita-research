import ReactMarkdown from "react-markdown";
import { useState } from "react";
import type { SessionRecord } from "../api";

function confidenceLabel(score: number): { label: string; className: string } {
  if (score >= 0.8) return { label: "High Confidence", className: "confidence--high" };
  if (score >= 0.6) return { label: "Moderate Confidence", className: "confidence--moderate" };
  if (score >= 0.4) return { label: "Low Confidence", className: "confidence--low" };
  return { label: "Uncertain", className: "confidence--uncertain" };
}

interface Props {
  result: SessionRecord;
}

export function ReportView({ result }: Props) {
  const { label, className } = confidenceLabel(result.confidence);
  const [copied, setCopied] = useState(false);

  const handleDownloadMarkdown = () => {
    const blob = new Blob([result.final_report], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `research-report-${result.session_id.slice(0, 8)}.md`;
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
    <div className="report-view">
      <div className="report-view__header">
        <div>
          <h2>{result.query}</h2>
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.4rem", alignItems: "center" }}>
            <span className={`confidence-badge ${className}`}>
              {label} · {Math.round(result.confidence * 100)}%
            </span>
            <span style={{ fontSize: "0.85rem", color: "#888" }}>
              {result.sources.length} sources analyzed
            </span>
          </div>
        </div>

        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            onClick={handleCopyReport}
            style={{
              padding: "0.4rem 0.8rem",
              borderRadius: "6px",
              border: "1px solid #444",
              background: "#222",
              color: "#fff",
              cursor: "pointer",
              fontSize: "0.85rem"
            }}
          >
            {copied ? "✓ Copied!" : "📋 Copy"}
          </button>
          <button
            onClick={handleDownloadMarkdown}
            style={{
              padding: "0.4rem 0.8rem",
              borderRadius: "6px",
              border: "1px solid #3b82f6",
              background: "#1d4ed8",
              color: "#fff",
              cursor: "pointer",
              fontSize: "0.85rem"
            }}
          >
            📥 Export .MD
          </button>
        </div>
      </div>

      {result.verified_claims.length > 0 && (
        <div className="claims">
          <div style={{ fontSize: "0.85rem", fontWeight: 600, marginBottom: "0.4rem", color: "#aaa" }}>
            VERIFIABLE CLAIM AUDIT TRAIL:
          </div>
          {result.verified_claims.map((claim, i) => (
            <div key={i} className={`claim ${claim.verified ? "claim--verified" : "claim--unverified"}`}>
              <span className="claim__icon">{claim.verified ? "✓" : "✗"}</span>
              <span className="claim__text">{claim.claim}</span>
              <span className="claim__confidence">{Math.round(claim.confidence * 100)}%</span>
            </div>
          ))}
        </div>
      )}

      <div className="report-view__body">
        <ReactMarkdown>{result.final_report}</ReactMarkdown>
      </div>
    </div>
  );
}
