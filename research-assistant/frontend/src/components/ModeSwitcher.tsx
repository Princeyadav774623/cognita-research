import { Icon, type IconName } from "./Icon";

/**
 * Picks what the workspace does, and says what each mode is for.
 *
 * This used to be two words in the header — "Deep Research" and "Chat with
 * Files" — which named the modes without explaining either, and sat far from
 * the box they governed. Here it sits directly under the input, where the
 * decision is actually made, and each option carries a line saying what it
 * does and where its answers come from.
 */

export type Mode = "research" | "rag";

const MODES: { id: Mode; label: string; blurb: string; icon: IconName; source: string }[] = [
  {
    id: "research",
    label: "Deep Research",
    blurb: "Searches the web, reads the sources, and checks every claim before answering.",
    icon: "search",
    source: "Answers come from the open web",
  },
  {
    id: "rag",
    label: "Chat with Files",
    blurb: "Ask questions about documents you upload. Answers quote your own files.",
    icon: "document",
    source: "Answers come from your uploads",
  },
];

interface Props {
  mode: Mode;
  onChange: (mode: Mode) => void;
  /** On the home page these are the way in, not a switch between two open
   *  panels — so nothing is marked active and each card reads as an invitation
   *  rather than a current state. */
  asEntry?: boolean;
}

export function ModeSwitcher({ mode, onChange, asEntry = false }: Props) {
  return (
    <div
      className={`mode-switch ${asEntry ? "mode-switch--entry" : ""}`}
      role={asEntry ? undefined : "tablist"}
      aria-label={asEntry ? undefined : "What to search"}
    >
      {MODES.map((m) => {
        const active = !asEntry && m.id === mode;
        return (
          <button
            key={m.id}
            type="button"
            role={asEntry ? undefined : "tab"}
            aria-selected={asEntry ? undefined : active}
            className={`mode-card ${active ? "mode-card--active" : ""}`}
            onClick={() => onChange(m.id)}
          >
            <span className="mode-card__icon"><Icon name={m.icon} size={18} /></span>
            <span className="mode-card__body">
              <span className="mode-card__label">
                {m.label}
                {active && <span className="mode-card__badge">Active</span>}
                {asEntry && <Icon name="chevron" size={14} className="mode-card__go" />}
              </span>
              <span className="mode-card__blurb">{m.blurb}</span>
              <span className="mode-card__source">
                <Icon name="sources" size={11} /> {m.source}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
