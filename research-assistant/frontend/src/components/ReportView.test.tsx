import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReportView } from "./ReportView";
import type { SessionRecord } from "../api";

function makeResult(over: Partial<SessionRecord> = {}): SessionRecord {
  return {
    session_id: "sess-1",
    query: "Is solar the cheapest electricity?",
    final_report: "# Summary\n\nSolar is cheapest.",
    sources: [
      { title: "IEA Report", url: "https://iea.org/report" },
      { title: "Our World in Data", url: "https://ourworldindata.org/energy" },
    ],
    confidence: 0.86,
    verified_claims: [],
    status: "complete",
    error: null,
    created_at: "2026-09-15T10:00:00Z",
    ...over,
  } as SessionRecord;
}

describe("ReportView", () => {
  it("labels confidence from the shared bands", () => {
    render(<ReportView result={makeResult({ confidence: 0.86 })} />);
    expect(screen.getByText(/High Grounding · 86%/)).toBeInTheDocument();
  });

  it("does not show a moderate colour with a low label", () => {
    // The badge switched at 0.8/0.5 and the label at 0.8/0.6/0.4, so 0.55
    // rendered a moderate-toned badge reading "Low Grounding".
    const { container } = render(<ReportView result={makeResult({ confidence: 0.55 })} />);
    expect(screen.getByText(/Low Grounding · 55%/)).toBeInTheDocument();
    expect(container.querySelector(".meta-badge--confidence-low")).toBeTruthy();
    expect(container.querySelector(".meta-badge--confidence-mod")).toBeFalsy();
  });

  it("offers a jump to the source a claim was checked against", async () => {
    const result = makeResult({
      verified_claims: [
        { claim: "Solar is cheapest", verified: true, confidence: 0.9, source: "https://iea.org/report" },
      ],
    });
    render(<ReportView result={result} />);

    const jump = screen.getByRole("button", { name: /see source/i });
    expect(jump).toBeInTheDocument();

    // jsdom has no layout, so scrollIntoView has to be stubbed to assert it ran.
    const scrollIntoView = vi.fn();
    const pill = document.getElementById("source-sess-1-0")!;
    pill.scrollIntoView = scrollIntoView;

    await userEvent.click(jump);
    expect(scrollIntoView).toHaveBeenCalled();
    expect(pill.getAttribute("style")).toContain("box-shadow");
  });

  it("matches a claim cited by title as well as by url", () => {
    const result = makeResult({
      verified_claims: [
        { claim: "Solar is cheapest", verified: true, confidence: 0.9, source: "IEA Report" },
      ],
    });
    render(<ReportView result={result} />);
    expect(screen.getByRole("button", { name: /see source/i })).toBeInTheDocument();
  });

  it("shows no jump when the citation matches nothing", () => {
    const result = makeResult({
      verified_claims: [
        { claim: "Unsupported", verified: false, confidence: 0.1, source: "Not found in sources" },
      ],
    });
    render(<ReportView result={result} />);
    expect(screen.queryByRole("button", { name: /see source/i })).toBeNull();
    expect(screen.getByText(/10% grounded/)).toBeInTheDocument();
  });

  it("renders every source as an external link", () => {
    render(<ReportView result={makeResult()} />);
    const link = screen.getByRole("link", { name: /IEA Report/ });
    expect(link).toHaveAttribute("href", "https://iea.org/report");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("omits the claims panel when nothing was verified", () => {
    render(<ReportView result={makeResult({ verified_claims: [] })} />);
    expect(screen.queryByText(/grounding audit/i)).toBeNull();
  });
});
