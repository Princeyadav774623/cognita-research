import { useState } from "react";
import { Icon } from "./Icon";

const EXAMPLES = [
  "What is LangGraph and how is it used for multi-agent systems?",
  "How does retrieval-augmented generation reduce LLM hallucination?",
  "What are the main benefits of using FastAPI over Flask?",
  "What are the best strategies to build wealth and become successful?",
];

interface Props {
  disabled: boolean;
  onSubmit: (query: string) => void;
}

export function QueryInput({ disabled, onSubmit }: Props) {
  const [value, setValue] = useState("");

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
  };

  return (
    <div>
      <div className="query-box">
        <input
          className="query-box__input"
          type="text"
          placeholder="Ask a complex research question..."
          value={value}
          maxLength={500}
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        <button
          type="button"
          className="query-box__btn"
          onClick={submit}
          disabled={disabled || !value.trim()}
        >
          {disabled ? "Synthesizing..." : <><Icon name="spark" size={15} /> Run Research</>}
        </button>
      </div>

      <div className="suggestion-chips">
        {EXAMPLES.map((ex) => (
          <button
            type="button"
            key={ex}
            className="suggestion-chip"
            disabled={disabled}
            onClick={() => {
              setValue(ex);
              onSubmit(ex);
            }}
          >
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}
