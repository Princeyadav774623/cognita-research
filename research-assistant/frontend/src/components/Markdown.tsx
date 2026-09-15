import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Chart, parseChartSpec } from "./Chart";

/**
 * One markdown renderer for the whole app.
 *
 * react-markdown on its own implements CommonMark, which has no tables. Models
 * write GFM pipe tables constantly, so every comparison table in a report
 * arrived as a wall of pipes and dashes on one line — the single worst thing
 * about the output, and invisible in code review because the markdown itself
 * was perfectly valid. remark-gfm also brings strikethrough, task lists and
 * autolinks.
 *
 * Diagrams render too: a ```mermaid fence becomes a picture. Some relationships
 * (a pipeline, a decision, a hierarchy) are genuinely faster to read as a
 * drawing than as three paragraphs describing the drawing.
 */

let mermaidReady: Promise<typeof import("mermaid").default> | null = null;

function loadMermaid(isDark: boolean) {
  if (!mermaidReady) {
    mermaidReady = import("mermaid").then((m) => {
      m.default.initialize({
        startOnLoad: false,
        securityLevel: "strict",   // diagram source is model output; no scripts, no click handlers
        theme: isDark ? "dark" : "neutral",
        fontFamily: "var(--font-sans)",
      });
      return m.default;
    });
  }
  return mermaidReady;
}

function MermaidBlock({ chart }: { chart: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const isDark = document.documentElement.getAttribute("data-theme") !== "light";
    const id = `m${Math.random().toString(36).slice(2)}`;

    loadMermaid(isDark)
      .then((mermaid) => mermaid.render(id, chart))
      .then(({ svg }) => {
        if (!cancelled && ref.current) ref.current.innerHTML = svg;
      })
      .catch(() => {
        // A model can emit mermaid that doesn't parse. Showing the source beats
        // showing a broken diagram or an error the reader can't act on.
        if (!cancelled) setFailed(true);
      });

    return () => { cancelled = true; };
  }, [chart]);

  if (failed) {
    return <pre className="md-code"><code>{chart}</code></pre>;
  }
  return <div className="md-diagram" ref={ref} role="img" aria-label="Diagram" />;
}

interface Props {
  children: string;
}

export function Markdown({ children }: Props) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        // Tables get their own scroll container so a wide one never makes the
        // whole page scroll sideways.
        table: ({ children: c }) => (
          <div className="md-table-wrap">
            <table className="md-table">{c}</table>
          </div>
        ),
        code: ({ className, children: c, ...rest }) => {
          const text = String(c ?? "");
          if (className === "language-mermaid") {
            return <MermaidBlock chart={text.replace(/\n$/, "")} />;
          }
          if (className === "language-chart") {
            const spec = parseChartSpec(text);
            // Malformed JSON falls through to a normal code block rather than
            // rendering an empty box the reader can't interpret.
            if (spec) return <Chart spec={spec} />;
          }
          return <code className={className} {...rest}>{c}</code>;
        },
        // Sources open in a new tab; a report is a document you read alongside
        // its references, not a place you navigate away from.
        a: ({ href, children: c }) => (
          <a href={href} target="_blank" rel="noopener noreferrer">{c}</a>
        ),
      }}
    >
      {children}
    </ReactMarkdown>
  );
}
