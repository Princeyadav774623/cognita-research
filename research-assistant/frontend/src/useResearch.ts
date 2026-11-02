import { useCallback, useRef, useState } from "react";
import {
  cancelResearch,
  fetchSession,
  runResearchStream,
  type ProgressEvent,
  type SessionRecord,
} from "./api";

export interface StepStatus {
  node: string;
  message: string;
}

type Phase = "idle" | "running" | "done" | "error";

// The research outlives the page now, so the page remembers which run it was
// watching: a refresh, or reopening the tab, reattaches instead of losing it.
const ACTIVE_KEY = "cognita.activeResearch";

interface ActiveRun {
  sessionId: string;
  query: string;
}

function saveActive(run: ActiveRun | null) {
  try {
    if (run) localStorage.setItem(ACTIVE_KEY, JSON.stringify(run));
    else localStorage.removeItem(ACTIVE_KEY);
  } catch {
    // Storage blocked (private mode, disabled cookies) — only resume is lost.
  }
}

function loadActive(): ActiveRun | null {
  try {
    const raw = localStorage.getItem(ACTIVE_KEY);
    return raw ? (JSON.parse(raw) as ActiveRun) : null;
  } catch {
    return null;
  }
}

export function useResearch() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [steps, setSteps] = useState<StepStatus[]>([]);
  // Report text as it streams in, before the saved session is fetched.
  const [streamedReport, setStreamedReport] = useState("");
  const [result, setResult] = useState<SessionRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<(() => void) | null>(null);
  const activeRef = useRef<ActiveRun | null>(null);

  const attach = useCallback((token: string, run: ActiveRun) => {
    closeRef.current?.();
    activeRef.current = run;
    saveActive(run);
    setPhase("running");
    setSteps([]);
    setResult(null);
    setError(null);
    setStreamedReport("");

    const finish = () => {
      activeRef.current = null;
      saveActive(null);
    };

    const onEvent = (event: ProgressEvent) => {
      if (event.type === "restart") {
        // Everything shown so far belongs to an attempt that was abandoned.
        setStreamedReport("");
        setSteps([{ node: "restart", message: event.message ?? "Starting over" }]);
      }
      if (event.type === "token" && event.text) {
        setStreamedReport((prev) => prev + event.text);
      }
      if (event.type === "progress") {
        setSteps((prev) => [
          ...prev,
          { node: event.node ?? event.step ?? "step", message: event.data?.message as string ?? "" },
        ]);
      }
      if (event.type === "error") {
        finish();
        setError(event.message ?? "Something went wrong");
        setPhase("error");
      }
      if (event.type === "complete") {
        finish();
        fetchSession(token, run.sessionId)
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

    closeRef.current = runResearchStream(token, run.query, onEvent, run.sessionId);
  }, []);

  const start = useCallback((token: string, query: string) => {
    attach(token, { sessionId: crypto.randomUUID(), query });
  }, [attach]);

  /** Pick up a run this browser was watching before a refresh. */
  const resume = useCallback((token: string) => {
    const run = loadActive();
    if (run && !activeRef.current) attach(token, run);
  }, [attach]);

  /** Stop watching. The run itself carries on and lands in history. */
  const reset = useCallback(() => {
    closeRef.current?.();
    closeRef.current = null;
    activeRef.current = null;
    saveActive(null);
    setPhase("idle");
    setSteps([]);
    setResult(null);
    setError(null);
    setStreamedReport("");
  }, []);

  /** Cancel the run on the server, which also returns its query to the allowance. */
  const stop = useCallback(async (token: string) => {
    const run = activeRef.current;
    reset();
    if (run) await cancelResearch(token, run.sessionId);
  }, [reset]);

  return { phase, steps, result, error, streamedReport, start, resume, reset, stop };
}
