import { useEffect, useRef, useState } from "react";

/**
 * The pipeline, drawn, while it runs.
 *
 * The five agents are the product's whole differentiator and they were shown
 * as a list of text that ticked over. Here the work is visible: evidence
 * travels along an edge, the receiving node takes over, and the reflective
 * loop is a line that actually goes backwards — which is the part people find
 * hardest to picture from prose.
 *
 * Inline SVG rather than a canvas or a 3D library: nine nodes and ten edges do
 * not need WebGL, and SVG inherits the theme's colours, scales without
 * blurring, and reads to a screen reader as the text description below it.
 */

interface Node {
  id: string;
  label: string;
  x: number;
  y: number;
}

// Laid out as the pipeline actually runs: a left-to-right spine, with the
// corpus hanging below the reader (it joins the same evidence set) and gap
// analysis sitting above, where its loop back to search is legible.
const NODES: Node[] = [
  { id: "triage",       label: "Triage",    x: 60,  y: 100 },
  { id: "planner",      label: "Plan",      x: 160, y: 100 },
  { id: "search",       label: "Search",    x: 265, y: 100 },
  { id: "read",         label: "Read",      x: 370, y: 100 },
  { id: "corpus",       label: "Your files", x: 370, y: 162 },
  { id: "analyze",      label: "Analyse",   x: 475, y: 100 },
  { id: "factcheck",    label: "Verify",    x: 580, y: 100 },
  { id: "gap_analysis", label: "Gaps",      x: 685, y: 100 },
  { id: "report",       label: "Report",    x: 790, y: 100 },
];

const EDGES: [string, string][] = [
  ["triage", "planner"], ["planner", "search"], ["search", "read"],
  ["read", "corpus"], ["corpus", "analyze"], ["read", "analyze"],
  ["analyze", "factcheck"], ["factcheck", "gap_analysis"], ["gap_analysis", "report"],
];

const byId = (id: string) => NODES.find((n) => n.id === id)!;

/** The reflective loop: gap analysis sends the run back to search when the
 *  evidence is thin. Drawn as an arc above the spine so it reads as a return
 *  path rather than another forward step. */
const LOOP_PATH = `M ${byId("gap_analysis").x} ${byId("gap_analysis").y - 20}
  C ${byId("gap_analysis").x - 60} ${byId("gap_analysis").y - 78},
    ${byId("search").x + 60} ${byId("search").y - 78},
    ${byId("search").x} ${byId("search").y - 20}`;

interface Props {
  /** Nodes already completed, in the order they finished. */
  completed: string[];
  active: string | null;
  running: boolean;
  /** True once the run has looped back to search at least once. */
  looped: boolean;
}

export function AgentGraph({ completed, active, running, looped }: Props) {
  const done = new Set(completed);
  const [reducedMotion, setReducedMotion] = useState(false);
  const liveRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const onChange = () => setReducedMotion(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const activeNode = active ? NODES.find((n) => n.id === active) : null;

  const edgeState = (from: string, to: string) => {
    // Live means work is flowing out of the stage that is running right now.
    // Keying this off the last *completed* node instead left no edge ever
    // live: by the time a node finished, its outgoing edge already counted as
    // done, so the travelling dot had nowhere to appear.
    if (running && from === active) return "live";
    if (done.has(from) && (done.has(to) || to === active)) return "done";
    return "idle";
  };

  return (
    <figure className="agent-graph">
      <svg viewBox="0 0 850 200" className="agent-graph__svg" role="img"
           aria-label="Diagram of the research pipeline, showing which stage is running">
        {/* Reflective loop, drawn first so nodes sit above it. */}
        <path
          d={LOOP_PATH}
          className={`agent-graph__loop ${looped ? "agent-graph__loop--taken" : ""}`}
          fill="none"
        />
        <text x={(byId("search").x + byId("gap_analysis").x) / 2} y={18}
              className="agent-graph__loop-label" textAnchor="middle">
          {looped ? "evidence was thin — searching again" : "loops back if evidence is thin"}
        </text>

        {EDGES.map(([from, to]) => {
          const a = byId(from), b = byId(to);
          const state = edgeState(from, to);
          return (
            <g key={`${from}-${to}`}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                    className={`agent-graph__edge agent-graph__edge--${state}`} />
              {/* A dot travelling the edge is the work being handed on. Only on
                  the edge leaving the stage that is currently running, so the
                  eye has one thing to follow rather than nine. */}
              {state === "live" && !reducedMotion && (
                <circle r="3.5" className="agent-graph__pulse">
                  <animateMotion dur="1.4s" repeatCount="indefinite"
                                 path={`M ${a.x} ${a.y} L ${b.x} ${b.y}`} />
                </circle>
              )}
            </g>
          );
        })}

        {NODES.map((n) => {
          const isDone = done.has(n.id);
          const isActive = n.id === active;
          return (
            <g key={n.id} className={`agent-graph__node ${isDone ? "is-done" : ""} ${isActive ? "is-active" : ""}`}>
              {isActive && !reducedMotion && (
                <circle cx={n.x} cy={n.y} r="16" className="agent-graph__halo" />
              )}
              <circle cx={n.x} cy={n.y} r="11" className="agent-graph__dot" />
              {isDone && (
                <path d={`M ${n.x - 4.5} ${n.y} l 3 3.5 l 6 -7`}
                      className="agent-graph__tick" fill="none" />
              )}
              <text x={n.x} y={n.y + 30} textAnchor="middle" className="agent-graph__label">
                {n.label}
              </text>
            </g>
          );
        })}
      </svg>

      {/* The same information as text. The diagram is decoration to a screen
          reader; this is not. */}
      <p className="agent-graph__status" aria-live="polite" ref={liveRef}>
        {running && activeNode
          ? `Running: ${activeNode.label}`
          : running
            ? "Starting"
            : `Finished ${completed.length} of ${NODES.length} stages`}
      </p>
    </figure>
  );
}
