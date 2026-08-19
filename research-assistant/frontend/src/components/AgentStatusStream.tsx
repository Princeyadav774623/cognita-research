import type { StepStatus } from "../useResearch";
import { Icon, type IconName } from "./Icon";

const NODE_INFO: Record<string, { label: string; icon: IconName }> = {
  triage: { label: "Assessing Question Complexity", icon: "sliders" },
  planner: { label: "Planning Research Strategy", icon: "compass" },
  search: { label: "Web Search & Gathering", icon: "search" },
  read: { label: "Reading & Sanitizing Documents", icon: "document" },
  corpus: { label: "Searching Your Knowledge Base", icon: "sources" },
  analyze: { label: "Cross-Source Synthesis", icon: "brain" },
  factcheck: { label: "Fact-Check Verification", icon: "verified" },
  gap_analysis: { label: "Reflective Gap Analysis", icon: "gap" },
  report: { label: "Final Report Compilation", icon: "report" },
};

interface Props {
  steps: StepStatus[];
  running: boolean;
}

export function AgentStatusStream({ steps, running }: Props) {
  if (steps.length === 0 && !running) return null;

  return (
    <div className="agent-stream">
      <div className="agent-stream__header">
        <div className="agent-stream__title">
          {running && <span className="agent-stream__pulse" />}
          <span>{running ? "Autonomous Agent Execution" : "Agent Execution Summary"}</span>
        </div>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem", color: "var(--text-muted)" }}>
          {steps.length} Steps Completed
        </span>
      </div>

      <div className="agent-steps">
        {steps.map((step, i) => {
          const info = NODE_INFO[step.node] || { label: step.node, icon: "spark" as IconName };
          return (
            <div key={i} className="agent-step">
              <span className="agent-step__node">
                <Icon name={info.icon} size={15} />
                {step.node}
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "0.2rem" }}>
                  {info.label}
                </div>
                {step.message && <div className="agent-step__msg">{step.message}</div>}
              </div>
            </div>
          );
        })}

        {running && (
          <div className="agent-step" style={{ borderLeftColor: "var(--border-strong)" }}>
            <span className="agent-step__node">
              <span className="agent-stream__pulse" style={{ display: "inline-block", margin: "0 2px" }} />
            </span>
            <div className="agent-step__msg" style={{ color: "var(--text-muted)", fontStyle: "italic" }}>
              Collaborating across agents and verifying citations...
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
