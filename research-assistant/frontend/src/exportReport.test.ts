import { describe, expect, it } from "vitest";
import { toBibTeX } from "./exportReport";
import type { SessionRecord } from "./api";

const base = {
  session_id: "sess-1",
  query: "Is solar the cheapest electricity?",
  final_report: "...",
  confidence: 0.8,
  verified_claims: [],
  status: "complete",
  error: null,
  created_at: "2026-09-15T10:00:00Z",
} as unknown as SessionRecord;

describe("toBibTeX", () => {
  it("emits one @misc entry per source with its url and access date", () => {
    const bib = toBibTeX({ ...base, sources: [
      { title: "Renewables 2025", url: "https://iea.org/reports/renewables-2025" },
    ] } as SessionRecord);

    expect(bib).toContain("@misc{");
    expect(bib).toContain("title        = {Renewables 2025}");
    expect(bib).toContain("\\url{https://iea.org/reports/renewables-2025}");
    expect(bib).toContain("urldate      = {2026-09-15}");
  });

  it("escapes characters BibTeX would read as markup", () => {
    const bib = toBibTeX({ ...base, sources: [
      { title: "Cost & Scale: 100% renewables {draft}", url: "https://example.org/a" },
    ] } as SessionRecord);

    expect(bib).toContain("Cost \\& Scale: 100\\% renewables \\{draft\\}");
  });

  it("builds a distinct key per source", () => {
    const bib = toBibTeX({ ...base, sources: [
      { title: "Solar costs", url: "https://iea.org/a" },
      { title: "Solar costs", url: "https://ourworldindata.org/b" },
    ] } as SessionRecord);

    const keys = [...bib.matchAll(/@misc\{([^,]+),/g)].map((m) => m[1]);
    expect(new Set(keys).size).toBe(2);
    expect(keys[0]).toContain("iea");
    expect(keys[1]).toContain("ourworldindata");
  });

  it("survives a source whose url is not parseable", () => {
    // Corpus documents are addressed as upload://filename.
    const bib = toBibTeX({ ...base, sources: [
      { title: "My thesis", url: "upload://thesis.pdf" },
    ] } as SessionRecord);

    expect(bib).toContain("@misc{");
    expect(bib).toContain("thesis.pdf");
  });

  it("produces a valid, empty bibliography when there are no sources", () => {
    const bib = toBibTeX({ ...base, sources: [] } as SessionRecord);
    expect(bib).toContain("0 references");
    expect(bib).not.toContain("@misc{");
  });
});
