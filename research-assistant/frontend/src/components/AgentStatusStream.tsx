import type { StepStatus } from "../useResearch";

const NODE_LABELS: Record<string, string> = {
  planner: "🧭 Planning research strategy & decomposing queries",
  search: "🔍 Searching the web",
  read: "📄 Reading & extracting verified sources",
  analyze: "🧠 Synthesizing cross-source findings",
  factcheck: "✅ Verifying factual claims",
  gap_analysis: "🔬 Assessing evidence depth & knowledge gaps",
  report: "📝 Writing final grounded report",
};

interface Props {
  steps: StepStatus[];
  running: boolean;
}

export function AgentStatusStream({ steps, running }: Props) {
  if (steps.length === 0 && !running) return null;

  return (
    <ul className="status-stream">
      {steps.map((step, i) => (
        <li key={i} className="status-stream__item status-stream__item--done">
          <span className="status-stream__label">{NODE_LABELS[step.node] ?? step.node}</span>
          {step.message && <span className="status-stream__message">{step.message}</span>}
        </li>
      ))}
      {running && (
        <li className="status-stream__item status-stream__item--active">
          <span className="status-stream__spinner" aria-hidden="true" />
          <span className="status-stream__label">Working…</span>
        </li>
      )}
    </ul>
  );
}
