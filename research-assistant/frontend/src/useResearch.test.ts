import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useResearch } from "./useResearch";
import type { ProgressEvent } from "./api";

// The WebSocket event handling is the stateful logic most likely to break
// silently: token accumulation, the complete-without-session-id branch, and
// the error transitions all had no coverage at all.
const mocks = vi.hoisted(() => ({
  emit: null as null | ((e: ProgressEvent) => void),
  sessionId: "",
  query: "",
  close: vi.fn(),
  fetchSession: vi.fn(),
  cancelResearch: vi.fn(),
}));

vi.mock("./api", () => ({
  runResearchStream: (
    _t: string, q: string, onEvent: (e: ProgressEvent) => void, sessionId: string,
  ) => {
    mocks.emit = onEvent;
    mocks.sessionId = sessionId;
    mocks.query = q;
    return mocks.close;
  },
  fetchSession: (...args: unknown[]) => mocks.fetchSession(...args),
  cancelResearch: (...args: unknown[]) => mocks.cancelResearch(...args),
}));

const send = (e: ProgressEvent) => act(() => { mocks.emit!(e); });

describe("useResearch", () => {
  beforeEach(() => {
    mocks.emit = null;
    mocks.close.mockClear();
    mocks.fetchSession.mockReset();
    mocks.cancelResearch.mockReset().mockResolvedValue(undefined);
    localStorage.clear();
  });

  it("starts idle and moves to running", () => {
    const { result } = renderHook(() => useResearch());
    expect(result.current.phase).toBe("idle");

    act(() => result.current.start("tok", "why is the sky blue"));
    expect(result.current.phase).toBe("running");
  });

  it("accumulates streamed tokens in order", () => {
    const { result } = renderHook(() => useResearch());
    act(() => result.current.start("tok", "q"));

    send({ type: "token", text: "Hello " });
    send({ type: "token", text: "world" });

    expect(result.current.streamedReport).toBe("Hello world");
  });

  it("records each progress step", () => {
    const { result } = renderHook(() => useResearch());
    act(() => result.current.start("tok", "q"));

    send({ type: "progress", node: "search", data: { message: "Found 12 sources" } });

    expect(result.current.steps).toEqual([{ node: "search", message: "Found 12 sources" }]);
  });

  it("loads the saved session once the run completes", async () => {
    const record = { session_id: "s1", final_report: "done" };
    mocks.fetchSession.mockResolvedValue(record);

    const { result } = renderHook(() => useResearch());
    act(() => result.current.start("tok", "q"));
    send({ type: "complete" });

    await waitFor(() => expect(result.current.phase).toBe("done"));
    expect(result.current.result).toEqual(record);
    // The id the client chose when it started the run, not one the server sent.
    expect(mocks.fetchSession).toHaveBeenCalledWith("tok", mocks.sessionId);
  });

  it("surfaces a server error message", () => {
    const { result } = renderHook(() => useResearch());
    act(() => result.current.start("tok", "q"));

    send({ type: "error", message: "Monthly quota exceeded (10/10)." });

    expect(result.current.phase).toBe("error");
    expect(result.current.error).toContain("quota");
  });

  it("reports a failure to load the finished report", async () => {
    mocks.fetchSession.mockRejectedValue(new Error("Session not found (404)"));

    const { result } = renderHook(() => useResearch());
    act(() => result.current.start("tok", "q"));
    send({ type: "complete" });

    await waitFor(() => expect(result.current.phase).toBe("error"));
    expect(result.current.error).toContain("404");
  });

  it("closes the socket and clears state on reset", () => {
    const { result } = renderHook(() => useResearch());
    act(() => result.current.start("tok", "q"));
    send({ type: "token", text: "partial" });

    act(() => result.current.reset());

    expect(mocks.close).toHaveBeenCalled();
    expect(result.current.phase).toBe("idle");
    expect(result.current.streamedReport).toBe("");
    expect(result.current.steps).toEqual([]);
  });

  it("clears the previous run when a new one starts", () => {
    const { result } = renderHook(() => useResearch());
    act(() => result.current.start("tok", "first"));
    send({ type: "token", text: "stale" });

    act(() => result.current.start("tok", "second"));

    expect(result.current.streamedReport).toBe("");
    expect(result.current.phase).toBe("running");
  });

  it("drops progress from an abandoned attempt when the run restarts", () => {
    const { result } = renderHook(() => useResearch());
    act(() => result.current.start("tok", "q"));
    send({ type: "progress", node: "search", data: { message: "Found 12 sources" } });
    send({ type: "token", text: "half a report" });

    send({ type: "restart", message: "Hit an error — retrying from the start" });

    expect(result.current.streamedReport).toBe("");
    expect(result.current.steps).toEqual([
      { node: "restart", message: "Hit an error — retrying from the start" },
    ]);
    expect(result.current.phase).toBe("running");
  });

  it("stop cancels the run on the server", async () => {
    const { result } = renderHook(() => useResearch());
    act(() => result.current.start("tok", "q"));
    const id = mocks.sessionId;

    await act(() => result.current.stop("tok"));

    // Closing the socket no longer stops the server-side run; only this does.
    expect(mocks.cancelResearch).toHaveBeenCalledWith("tok", id);
    expect(result.current.phase).toBe("idle");
  });

  it("resumes the run it was watching after a reload", () => {
    const first = renderHook(() => useResearch());
    act(() => first.result.current.start("tok", "why is the sky blue"));
    const id = mocks.sessionId;
    first.unmount();

    // A fresh hook, as after a page reload.
    const { result } = renderHook(() => useResearch());
    act(() => result.current.resume("tok2"));

    expect(result.current.phase).toBe("running");
    expect(mocks.sessionId).toBe(id);
    expect(mocks.query).toBe("why is the sky blue");
  });

  it("forgets the run once it finishes", async () => {
    mocks.fetchSession.mockResolvedValue({ session_id: "x" });
    const { result } = renderHook(() => useResearch());
    act(() => result.current.start("tok", "q"));
    send({ type: "complete" });
    await waitFor(() => expect(result.current.phase).toBe("done"));

    const next = renderHook(() => useResearch());
    act(() => next.result.current.resume("tok"));
    expect(next.result.current.phase).toBe("idle");
  });
});
