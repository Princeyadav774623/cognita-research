import { useCallback, useRef, useState } from "react";
import { runResearchStream, fetchSession, type ProgressEvent, type SessionRecord } from "./api";

export interface StepStatus {
  node: string;
  message: string;
}

type Phase = "idle" | "running" | "done" | "error";

export function useResearch() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [steps, setSteps] = useState<StepStatus[]>([]);
  const [result, setResult] = useState<SessionRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<(() => void) | null>(null);

  const start = useCallback((token: string, query: string) => {
    setPhase("running");
    setSteps([]);
    setResult(null);
    setError(null);

    let sessionId = "";

    const onEvent = (event: ProgressEvent) => {
      if (event.type === "start" && event.session_id) {
        sessionId = event.session_id;
      }
      if (event.type === "progress") {
        setSteps((prev) => [
          ...prev,
          { node: event.node ?? event.step ?? "step", message: event.data?.message as string ?? "" },
        ]);
      }
      if (event.type === "error") {
        setError(event.message ?? "Something went wrong");
        setPhase("error");
      }
      if (event.type === "complete") {
        if (!sessionId) {
          setError("Research finished but no session id was returned");
          setPhase("error");
          return;
        }
        fetchSession(token, sessionId)
          .then((record) => {
            setResult(record);
            setPhase("done");
          })
          .catch((e) => {
            setError(e instanceof Error ? e.message : "Failed to load result");
            setPhase("error");
          });
      }
    };

    closeRef.current = runResearchStream(token, query, onEvent);
  }, []);

  const reset = useCallback(() => {
    closeRef.current?.();
    setPhase("idle");
    setSteps([]);
    setResult(null);
    setError(null);
  }, []);

  return { phase, steps, result, error, start, reset };
}
