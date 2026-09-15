import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useResearch } from "./useResearch";
import type { ProgressEvent } from "./api";

// The WebSocket event handling is the stateful logic most likely to break
// silently: token accumulation, the complete-without-session-id branch, and
// the error transitions all had no coverage at all.
const mocks = vi.hoisted(() => ({
  emit: null as null | ((e: ProgressEvent) => void),
  close: vi.fn(),
  fetchSession: vi.fn(),
}));

vi.mock("./api", () => ({
  runResearchStream: (_t: string, _q: string, onEvent: (e: ProgressEvent) => void) => {
    mocks.emit = onEvent;
    return mocks.close;
  },
  fetchSession: (...args: unknown[]) => mocks.fetchSession(...args),
}));

const send = (e: ProgressEvent) => act(() => { mocks.emit!(e); });

describe("useResearch", () => {
  beforeEach(() => {
    mocks.emit = null;
    mocks.close.mockClear();
    mocks.fetchSession.mockReset();
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
    send({ type: "start", session_id: "s1" });
    send({ type: "complete" });

    await waitFor(() => expect(result.current.phase).toBe("done"));
    expect(result.current.result).toEqual(record);
    expect(mocks.fetchSession).toHaveBeenCalledWith("tok", "s1");
  });

  it("errors rather than hanging when completion carries no session id", async () => {
    const { result } = renderHook(() => useResearch());
    act(() => result.current.start("tok", "q"));
    send({ type: "complete" });

    await waitFor(() => expect(result.current.phase).toBe("error"));
    expect(result.current.error).toMatch(/no session id/i);
    expect(mocks.fetchSession).not.toHaveBeenCalled();
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
    send({ type: "start", session_id: "s1" });
    send({ type: "complete" });

    await waitFor(() => expect(result.current.phase).toBe("error"));
    expect(result.current.error).toContain("404");
  });

  it("closes the socket and clears state on reset", () => {
    const { result } = renderHook(() => useResearch());
    act(() => result.current.start("tok", "q"));
    send({ type: "token", text: "partial" });

    act(() => result.current.reset());

    // Closing is what triggers the server-side quota refund, so it must
    // actually happen — not just clear the UI.
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
});
