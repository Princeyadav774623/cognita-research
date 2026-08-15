import { useState } from "react";

const EXAMPLES = [
  "What is LangGraph and how is it used for multi-agent systems?",
  "What are the main benefits of using FastAPI over Flask?",
  "How does retrieval-augmented generation reduce LLM hallucination?",
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
    <div className="query-input">
      <div className="query-input__row">
        <input
          type="text"
          placeholder="Ask a research question…"
          value={value}
          maxLength={500}
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        <button onClick={submit} disabled={disabled || !value.trim()}>
          {disabled ? "Researching…" : "Research"}
        </button>
      </div>
      <div className="query-input__examples">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            className="example-chip"
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
