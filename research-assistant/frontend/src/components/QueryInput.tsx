import { useEffect, useRef, useState } from "react";
import { Icon } from "./Icon";

const EXAMPLES = [
  "What is LangGraph and how is it used for multi-agent systems?",
  "How does retrieval-augmented generation reduce LLM hallucination?",
  "What are the main benefits of using FastAPI over Flask?",
  "What are the best strategies to build wealth and become successful?",
];

const MAX_CHARS = 500;
// Below this many characters left, the count starts showing. Always-on it is
// noise; only near the ceiling is it information.
const COUNTER_VISIBLE_FROM = 100;

interface Props {
  disabled: boolean;
  onSubmit: (query: string) => void;
}

export function QueryInput({ disabled, onSubmit }: Props) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Grow with the text. A single-line input meant someone writing a genuinely
  // complex question could not see the start of it.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
  };

  const remaining = MAX_CHARS - value.length;
  const showCounter = remaining <= COUNTER_VISIBLE_FROM;

  return (
    <div>
      <div className="query-box">
        <textarea
          ref={inputRef}
          id="research-query"
          className="query-box__input"
          rows={1}
          placeholder="Ask a complex research question..."
          value={value}
          maxLength={MAX_CHARS}
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            // Enter submits; Shift+Enter and Cmd/Ctrl+Enter are the escape
            // hatches for writing a multi-line question.
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              submit();
            } else if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button
          type="button"
          className="query-box__btn"
          onClick={submit}
          disabled={disabled || !value.trim()}
        >
          {disabled ? "Researching..." : <><Icon name="spark" size={15} /> Run Research</>}
        </button>
      </div>

      {showCounter && (
        <div className={`query-box__counter ${remaining === 0 ? "query-box__counter--full" : ""}`} aria-live="polite">
          {remaining === 0
            ? `Character limit reached (${MAX_CHARS})`
            : `${remaining} characters left`}
        </div>
      )}

      <div className="suggestion-chips">
        {EXAMPLES.map((ex) => (
          <button
            type="button"
            key={ex}
            className="suggestion-chip"
            disabled={disabled}
            // Fills the box rather than running immediately. These used to
            // submit on click, so one stray tap spent a query — 10% of a free
            // month's allowance, with no confirmation and no undo.
            onClick={() => {
              setValue(ex);
              inputRef.current?.focus();
            }}
          >
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}
