import { useEffect, useState } from "react";
import type { StepStatus } from "../useResearch";
import { Icon, type IconName } from "./Icon";
import { AgentGraph } from "./AgentGraph";

/** The pipeline in execution order. Showing the whole sequence up front means
 *  a two-minute wait has a shape: the reader can see what is left, not just
 *  what has happened. The reflective loop can revisit earlier stages, so
 *  progress is measured by how far through the sequence we have reached
 *  rather than by counting events. */
const PIPELINE: { node: string; label: string; icon: IconName }[] = [
  { node: "triage", label: "Assessing question complexity", icon: "sliders" },
  { node: "planner", label: "Planning research strategy", icon: "compass" },
  { node: "search", label: "Searching the web", icon: "search" },
  { node: "read", label: "Reading documents", icon: "document" },
  { node: "corpus", label: "Searching your knowledge base", icon: "sources" },
  { node: "analyze", label: "Synthesising across sources", icon: "brain" },
  { node: "factcheck", label: "Verifying claims", icon: "verified" },
  { node: "gap_analysis", label: "Checking for gaps", icon: "gap" },
  { node: "report", label: "Writing the report", icon: "report" },
];

function useElapsed(running: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!running) return;
    setSeconds(0);
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [running]);
  return seconds;
}

function formatElapsed(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m > 0 ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

interface Props {
  steps: StepStatus[];
  running: boolean;
}

export function AgentStatusStream({ steps, running }: Props) {
  const elapsed = useElapsed(running);
  if (steps.length === 0 && !running) return null;

  const messages = new Map<string, string>();
  for (const s of steps) if (s.message) messages.set(s.node, s.message);

  const reached = steps.length
    ? Math.max(...steps.map((s) => PIPELINE.findIndex((p) => p.node === s.node)))
    : -1;
  const done = reached + 1;
  // A pass through the loop can revisit stages, so this counts how far the run
  // has got, never more than the pipeline length.
  const completed = Math.min(done, PIPELINE.length);
  const pct = Math.round((completed / PIPELINE.length) * 100);

  return (
    <div className="agent-stream">
      <div className="agent-stream__header">
        <div className="agent-stream__title">
          {running && <span className="agent-stream__pulse" />}
          <span>{running ? "Researching" : "Agent execution summary"}</span>
        </div>
        <span className="agent-stream__counter">
          Step {completed} of {PIPELINE.length}
          {running && ` · ${formatElapsed(elapsed)}`}
        </span>
      </div>

      {/* The five agents are the product's differentiator and were shown only
          as a ticking list of text. */}
      <AgentGraph
        completed={PIPELINE.slice(0, completed).map((p) => p.node)}
        active={running && completed < PIPELINE.length ? PIPELINE[completed].node : null}
        running={running}
        looped={steps.filter((s) => s.node === "search").length > 1}
      />

      <div
        className="agent-progress"
        role="progressbar"
        aria-valuenow={completed}
        aria-valuemin={0}
        aria-valuemax={PIPELINE.length}
        aria-label="Research progress"
      >
        <span className="agent-progress__fill" style={{ width: `${pct}%` }} />
      </div>

      {/* The whole experience of this product is watching these arrive. Without
          a live region a screen-reader user gets nothing at all between
          submitting and the report landing. */}
      <ol className="agent-steps" aria-live="polite" aria-busy={running}>
        {PIPELINE.map((stage, i) => {
          const state = i < completed ? "done" : i === completed && running ? "active" : "pending";
          const detail = messages.get(stage.node);
          return (
            <li key={stage.node} className={`agent-step agent-step--${state}`}>
              <span className="agent-step__node">
                {state === "active" ? (
                  <span className="agent-stream__pulse" />
                ) : (
                  <Icon name={stage.icon} size={15} />
                )}
              </span>
              <div className="agent-step__body">
                <div className="agent-step__label">{stage.label}</div>
                {detail && <div className="agent-step__msg">{detail}</div>}
              </div>
              {state === "done" && <span className="agent-step__tick" aria-hidden="true">✓</span>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
