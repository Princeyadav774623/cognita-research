/**
 * Build the Cognita project report as a .docx.
 *
 * Mirrors docs/Cognita-Project-Report.html chapter for chapter. Figures are the
 * same SVGs, rasterised at 2x so they stay sharp in print.
 */
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  ImageRun, PageBreak, TableOfContents, LevelFormat, convertInchesToTwip,
  Bookmark, InternalHyperlink,
} = require("docx");

/** Chapter titles, in order. Used for the static contents list and to
 *  bookmark each H1 so the entries link. */
const CHAPTERS = [
  "1. Introduction and Problem Statement",
  "2. Software Requirements Specification",
  "3. System Architecture",
  "4. The Agent Pipeline",
  "5. Retrieval-Augmented Generation Subsystem",
  "6. Data Layer and Security",
  "7. Verification and Confidence Scoring",
  "8. Testing and Continuous Integration",
  "9. Results and Measurements",
  "10. Evaluation, Limitations and Future Work",
  "11. SRS Diagrams",
  "Appendix: Environment and Reproduction",
];
const anchorFor = (t) => "ch" + CHAPTERS.indexOf(t);

const FIG = process.argv[2];
const OUT = process.argv[3];

/* ---- palette, matching the HTML report ---- */
const INK = "16150F", INK2 = "474338", INK3 = "7C7566";
const BRONZE = "A06B21", TEAL = "1D5F63", RULE = "DDD6C8", PAPER2 = "FAF7F1";
/* The page itself is the HTML report's --paper; anything that is a card in the
   HTML (tables, figure frames) keeps --card white so it still lifts off it. */
const PAPER = "F4F1EA", CARD = "FFFFFF";

const PAGE_W = convertInchesToTwip(8.5) - convertInchesToTwip(1.25) * 2; // usable width

/* ---- helpers ---- */
const P = (text, o = {}) => new Paragraph({
  spacing: { after: o.after ?? 140, line: o.line ?? 300 },
  alignment: o.align,
  children: [new TextRun({
    text, font: o.font ?? "Georgia", size: o.size ?? 21,
    color: o.color ?? INK2, bold: o.bold, italics: o.italics,
  })],
  ...(o.border ? { border: o.border } : {}),
});

const H1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1, pageBreakBefore: true,
  spacing: { before: 240, after: 200 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: INK, space: 6 } },
  children: [new Bookmark({
    id: anchorFor(text),
    children: [new TextRun({ text, font: "Calibri", size: 34, bold: true, color: INK })],
  })],
});

const H2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2, spacing: { before: 260, after: 120 },
  children: [new TextRun({ text, font: "Calibri", size: 24, bold: true, color: INK })],
});

const EYEBROW = (text) => new Paragraph({
  spacing: { after: 60 },
  children: [new TextRun({ text: text.toUpperCase(), font: "Consolas", size: 15, color: BRONZE, characterSpacing: 30 })],
});

const BULLET = (text, level = 0) => new Paragraph({
  numbering: { reference: "bullets", level },
  spacing: { after: 90, line: 280 },
  children: [new TextRun({ text, font: "Georgia", size: 21, color: INK2 })],
});

/** A quoted lead-in, set off by a left rule rather than italics. */
const LEDE = (text) => new Paragraph({
  spacing: { before: 120, after: 200, line: 320 },
  indent: { left: 240 },
  border: { left: { style: BorderStyle.SINGLE, size: 18, color: BRONZE, space: 12 } },
  children: [new TextRun({ text, font: "Georgia", size: 23, color: INK })],
});

/** Callout box. `tone` picks the accent colour. */
const NOTE = (label, text, tone = TEAL) => new Table({
  width: { size: PAGE_W, type: WidthType.DXA },
  columnWidths: [PAGE_W],
  borders: {
    top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE },
    right: { style: BorderStyle.NONE }, insideHorizontal: { style: BorderStyle.NONE },
    insideVertical: { style: BorderStyle.NONE },
    left: { style: BorderStyle.SINGLE, size: 18, color: tone },
  },
  rows: [new TableRow({
    children: [new TableCell({
      width: { size: PAGE_W, type: WidthType.DXA },
      shading: { type: ShadingType.CLEAR, fill: PAPER2 },
      margins: { top: 160, bottom: 160, left: 200, right: 200 },
      children: [new Paragraph({
        spacing: { after: 0, line: 290 },
        children: [
          new TextRun({ text: label + " ", font: "Calibri", size: 20, bold: true, color: tone }),
          new TextRun({ text, font: "Georgia", size: 20, color: INK2 }),
        ],
      })],
    })],
  })],
});

/** Table with a header row. `widths` are fractions of the page width. */
function TBL(headers, rows, widths) {
  const cols = widths.map((w) => Math.round(PAGE_W * w));
  const cell = (text, opts = {}) => new TableCell({
    width: { size: opts.w, type: WidthType.DXA },
    shading: { type: ShadingType.CLEAR, fill: opts.head ? PAPER2 : CARD },
    margins: { top: 90, bottom: 90, left: 120, right: 120 },
    children: [new Paragraph({
      spacing: { after: 0, line: 260 },
      children: [new TextRun({
        text: String(text),
        font: opts.mono ? "Consolas" : "Calibri",
        size: opts.head ? 16 : 18,
        bold: opts.head || opts.bold,
        color: opts.head ? INK3 : INK2,
        allCaps: opts.head,
      })],
    })],
  });

  return new Table({
    width: { size: PAGE_W, type: WidthType.DXA },
    columnWidths: cols,
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      left: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      right: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      insideVertical: { style: BorderStyle.SINGLE, size: 2, color: RULE },
    },
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((h, i) => cell(h, { head: true, w: cols[i] })),
      }),
      ...rows.map((r) => new TableRow({
        children: r.map((c, i) => cell(c, { w: cols[i], bold: i === 0 && r.length > 2 })),
      })),
    ],
  });
}

/* ---- product badges ----
 * Cognita is two products over one platform. The HTML report marks every
 * chapter with which of the three it belongs to; these are the Word equivalent,
 * as shaded runs rather than images so they stay searchable and selectable. */
const TAG_STYLE = {
  research: { fill: "FAF2E6", color: "7D5115", label: "DEEP RESEARCH" },
  files:    { fill: "EDF3F3", color: "1D5F63", label: "CHAT WITH FILES" },
  shared:   { fill: "F2F1EE", color: "7C7566", label: "SHARED PLATFORM" },
};

const TAG = (kind) => {
  const t = TAG_STYLE[kind];
  return new TextRun({
    text: "  " + t.label + "  ", font: "Consolas", size: 13, bold: true,
    color: t.color, characterSpacing: 20,
    shading: { type: ShadingType.CLEAR, fill: t.fill },
  });
};

/** The badge row that sits under a chapter heading. */
const TAGS = (...kinds) => new Paragraph({
  spacing: { before: 0, after: 200 },
  children: kinds.flatMap((k, i) => i === 0
    ? [TAG(k)]
    : [new TextRun({ text: "   ", size: 13 }), TAG(k)]),
});

/** Figure: image plus a caption beneath it. */
function FIGURE(file, widthIn, number, title, caption) {
  const data = fs.readFileSync(path.join(FIG, file));
  const w = Math.round(widthIn * 96);
  const meta = {
    1: [880, 500], 3: [860, 400], 4: [860, 240], 5: [700, 220], 9: [700, 260],
    "11.1": [880, 390], "11.2": [880, 360], "11.3": [880, 330], "11.4": [880, 400],
    "11.5": [880, 520], "11.6": [880, 440], "11.7": [880, 350], "11.8": [880, 340],
    "11.9": [880, 545],
  };
  const [nw, nh] = meta[number];
  return [
    new Paragraph({
      spacing: { before: 200, after: 80 },
      alignment: AlignmentType.CENTER,
      children: [new ImageRun({
        type: "png", data,
        transformation: { width: w, height: Math.round((w * nh) / nw) },
      })],
    }),
    new Paragraph({
      spacing: { after: 220 }, alignment: AlignmentType.CENTER,
      children: [
        new TextRun({ text: `Figure ${number} — ${title}. `, font: "Calibri", size: 17, bold: true, color: INK }),
        new TextRun({ text: caption, font: "Georgia", size: 17, italics: true, color: INK3 }),
      ],
    }),
  ];
}

/* ====================== DOCUMENT ====================== */
const children = [];

/* ---- cover ---- */
children.push(
  new Paragraph({ spacing: { before: 1400, after: 200 },
    children: [new TextRun({ text: "PROJECT REPORT · ENGINEERING & EVALUATION", font: "Consolas", size: 16, color: BRONZE, characterSpacing: 40 })] }),
  new Paragraph({ spacing: { after: 200 },
    children: [new TextRun({ text: "Cognita", font: "Calibri", size: 76, bold: true, color: INK })] }),
  new Paragraph({ spacing: { after: 320 },
    children: [new TextRun({ text: "Research that shows its working", font: "Georgia", size: 40, italics: true, color: BRONZE })] }),
  new Paragraph({ spacing: { after: 500, line: 320 },
    children: [new TextRun({ text: "A multi-agent research assistant that plans a question, searches the web and the user's own documents, verifies every claim against independent sources, and reports how confident it is — and why.", font: "Georgia", size: 23, color: INK2 })] }),
);
children.push(TBL(
  ["Field", "Value"],
  [["Author", "Prince Yadav"], ["Report date", "16 September 2026"],
   ["Codebase", "17,323 lines (8,807 backend · 8,516 frontend)"],
   ["Automated tests", "196 passing (165 backend · 31 frontend)"],
   ["Repository", "cognita-research"]],
  [0.3, 0.7]));

/** Which of the two products (or the shared platform) each chapter belongs to.
 *  Shown under every chapter heading and beside every contents entry, so the
 *  boundary between the two products is visible without reading for it. */
const CONTENTS_TAGS = {
  "1. Introduction and Problem Statement": ["shared"],
  "2. Software Requirements Specification": ["research", "files", "shared"],
  "3. System Architecture": ["shared"],
  "4. The Agent Pipeline": ["research"],
  "5. Retrieval-Augmented Generation Subsystem": ["files"],
  "6. Data Layer and Security": ["shared"],
  "7. Verification and Confidence Scoring": ["research"],
  "8. Testing and Continuous Integration": ["shared"],
  "9. Results and Measurements": ["research", "files"],
  "10. Evaluation, Limitations and Future Work": ["research", "files", "shared"],
  "11. SRS Diagrams": ["research", "files", "shared"],
  "Appendix: Environment and Reproduction": ["shared"],
};

/* ---- contents ---- */
children.push(
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ spacing: { after: 240 },
    children: [new TextRun({ text: "CONTENTS", font: "Calibri", size: 26, bold: true, color: INK })] }),
  ...CHAPTERS.map((title) => new Paragraph({
    spacing: { after: 100, line: 280 },
    children: [
      new InternalHyperlink({
        anchor: anchorFor(title),
        children: [new TextRun({ text: title, font: "Georgia", size: 21, color: INK2 })],
      }),
      // Which product the chapter belongs to, visible before the reader opens it.
      ...(CONTENTS_TAGS[title] ?? []).flatMap((k) => [
        new TextRun({ text: "  ", size: 13 }), TAG(k),
      ]),
    ],
  })),
);

/* ---- CH 1 ---- */
children.push(H1("1. Introduction and Problem Statement"));
children.push(TAGS("shared"));
children.push(LEDE("A language model asked a research question will produce a fluent, confident, well-structured answer whether or not it has any basis for it. The failure is not that it is sometimes wrong; it is that a wrong answer is indistinguishable from a right one."));
children.push(H2("1.1 The problem"));
children.push(P("Retrieval-augmented generation is the usual response: give the model source documents and instruct it to answer from them. This helps, but it moves the problem rather than solving it. The model can still assert things the sources do not support, cite a document that does not contain the claim, or answer a question the sources never addressed. A reader has no way to tell."));
children.push(P("Cognita's premise is that a research tool's output is only as valuable as the reader's ability to check it. Three properties follow:"));
children.push(BULLET("Every claim traces to a source. Citations must resolve to a document the system actually read, and that must be verified rather than trusted."));
children.push(BULLET("Verification must be independent. Checking a claim against the same text it was summarised from proves only that the summary was faithful."));
children.push(BULLET("Confidence must be honest. A score that does not reflect the quality of the underlying evidence is decoration, and worse than no score at all."));
children.push(H2("1.2 Two products, one platform"));
children.push(P("Cognita is not one tool. It is two separate products, reached from the home page as two separate entry points and running as two separate pages with two separate query boxes. They answer different kinds of question, and the difference between them is worth stating before anything else in this report, because every chapter that follows belongs to one of them or to the platform beneath both."));
children.push(TBL(["", "Deep Research", "Chat with Files"], [
  ["Entry point", "/#research", "/#files"],
  ["What you give it", "A question, typed. Nothing to upload.", "Your documents, uploaded first. No files, nothing to ask."],
  ["Where the evidence comes from", "The open web — the system goes and finds it", "Your own corpus — you supply it"],
  ["How it works", "A nine-node agent pipeline that plans, searches, reads, fact-checks and scores", "Ingestion, then hybrid retrieval over your chunks with a grading loop"],
  ["What you get back", "A cited report with a confidence score", "An answer grounded in your files, with the passages it used"],
  ["How it fails safely", "Re-searches, then reports low confidence", "Declines to answer"],
  ["Described in", "Chapters 4 and 7", "Chapter 5"],
  ["Measured in", "9.2, 9.3, 9.4", "9.1 (SQuAD 2.0)"],
], [0.26, 0.37, 0.37]));
children.push(new Paragraph({ spacing: { after: 160 }, children: [] }));
children.push(...FIGURE("fig1-boundary.png", 6.3, 1, "The two products and the platform they share",
  "Each product owns its own pipeline and its own source of evidence. Everything in the grey band is shared by both and belongs to neither. The dashed line is the single place the two meet."));
children.push(P("The two are not hermetically sealed, and it would be dishonest to draw them that way. One connection exists, marked in the figure above: the corpus node in the research pipeline can fold your uploaded documents into the evidence set alongside the web (FR-6). That is Deep Research borrowing the other product's corpus — not evidence that Chat with Files is a component of the research pipeline. It is a product in its own right, with its own page, its own retrieval path and its own benchmark."));
children.push(P("Below both sits a platform neither of them owns: accounts and quota, tenant isolation enforced in the database, LLM invocation with retry and model fallback, the token ledger, and the schema. Chapters 3, 6 and 8 describe that layer, and apply to both products equally."));
children.push(EYEBROW("How to read this report"));
children.push(P("Every chapter opens with a badge saying which of the three it belongs to, so the boundary is visible without having to hold it in mind:"));
children.push(TAGS("research", "files", "shared"));
children.push(H2("1.3 What this report covers"));
children.push(P("Chapters 2 to 8 describe requirements, architecture and implementation. Chapter 9 reports measurements taken from the running system — every figure in it was produced by executing the software, not estimated. Chapter 10 states plainly what remains unproven."));
children.push(H1("2. Software Requirements Specification"));
children.push(TAGS("research", "files", "shared"));
children.push(H2("2.1 Purpose and intended audience"));
children.push(P("This specification describes a web application delivering verifiable research answers. Its users are researchers, analysts and students who need an answer they can defend, not merely an answer they can read."));
children.push(H2("2.2 Functional requirements"));
children.push(TBL(["ID", "Product", "Requirement", "Priority", "Status"], [
  ["FR-1", "Research", "Accept a natural-language research question up to 500 characters.", "Must", "Implemented"],
  ["FR-2", "Research", "Decompose a question into 3–5 targeted sub-queries before searching.", "Must", "Implemented"],
  ["FR-3", "Research", "Classify question complexity and scale research depth accordingly.", "Should", "Implemented"],
  ["FR-4", "Research", "Search the open web and extract full text from HTML and PDF sources.", "Must", "Implemented"],
  ["FR-5", "Research", "Disclose when a source degraded to a search snippet rather than full text.", "Must", "Implemented"],
  ["FR-6", "Research + Files", "Search the user's uploaded documents as part of the same evidence set.", "Must", "Implemented"],
  ["FR-7", "Research", "Extract key factual claims and verify each against retrieved evidence.", "Must", "Implemented"],
  ["FR-8", "Research", "Corroborate claims against sources the draft was not written from.", "Must", "Implemented"],
  ["FR-9", "Research", "Re-search when gap analysis finds the evidence insufficient.", "Should", "Implemented"],
  ["FR-10", "Research", "Validate that every citation resolves to a source actually read.", "Must", "Implemented"],
  ["FR-11", "Research", "Report a confidence score with the factors that produced it.", "Must", "Implemented"],
  ["FR-12", "Research", "Stream progress and the report itself as they are produced.", "Should", "Implemented"],
  ["FR-13", "Files", "Upload PDF, DOCX, TXT, MD and images (OCR), up to 15 MB.", "Must", "Implemented"],
  ["FR-14", "Files", "Decline to answer when retrieved evidence is insufficient.", "Must", "Implemented"],
  ["FR-15", "Research", "Export a report as Markdown, BibTeX and PDF.", "Should", "Implemented"],
  ["FR-16", "Shared", "Enforce a monthly query allowance, refunding on failure.", "Must", "Implemented"],
  ["FR-17", "Shared", "Delete all user data on request (GDPR erasure).", "Must", "Implemented"],
], [0.08, 0.16, 0.47, 0.11, 0.18]));

children.push(H2("2.3 Non-functional requirements"));
children.push(TBL(["ID", "Category", "Requirement", "Verified by"], [
  ["NFR-1", "Security", "One tenant's data must be unreachable by another, enforced at the database.", "CI gate"],
  ["NFR-2", "Security", "Uploaded documents must not be able to alter system behaviour.", "Live injection test"],
  ["NFR-3", "Security", "Credentials must never appear in logs.", "Code review"],
  ["NFR-4", "Performance", "RAG answer latency under 5 s at p50.", "Measured: 2.0 s"],
  ["NFR-5", "Performance", "Vector search must not degrade linearly with corpus size.", "HNSW index"],
  ["NFR-6", "Reliability", "Transient provider failures retried; permanent ones not.", "26 unit tests"],
  ["NFR-7", "Reliability", "A restart must not strand an upload indefinitely.", "Stale-job reaper"],
  ["NFR-8", "Accessibility", "WCAG 2.1 AA contrast; visible focus; 44 px touch targets.", "Measured in browser"],
  ["NFR-9", "Observability", "Token usage and cost recorded per research run.", "Persisted per session"],
  ["NFR-10", "Portability", "Schema changes applied by versioned migrations.", "Alembic, 4 revisions"],
], [0.1, 0.16, 0.48, 0.26]));

children.push(H2("2.4 Constraints"));
children.push(BULLET("Postgres only. pgvector and row-level security are both required; SQLite is rejected at startup."));
children.push(BULLET("Free-tier inference. Groq's limits — 8,000 tokens/minute and 200,000 tokens/day — shape batching and retry behaviour throughout."));
children.push(BULLET("Two database roles. An owner role for migrations, a low-privilege role for runtime, or row-level security has no effect."));

/* ---- CH 3 ---- */
children.push(H1("3. System Architecture"));
children.push(TAGS("shared"));
children.push(LEDE("Three tiers: a React single-page application, a FastAPI service hosting a LangGraph state machine, and Postgres with pgvector holding both relational and vector data."));
children.push(...FIGURE("fig3-architecture.png", 6.3, 3, "System architecture",
  "Request paths are solid; the WebSocket carries streamed progress and report tokens. Every runtime query passes through the low-privilege role so row-level security applies."));
children.push(H2("3.1 Technology decisions and their reasons"));
children.push(TBL(["Layer", "Choice", "Why this rather than the obvious alternative"], [
  ["Orchestration", "LangGraph", "The pipeline needs to loop back when evidence is thin. A chain cannot; a graph with conditional edges can."],
  ["Vector store", "pgvector", "Vectors beside tenant data means one RLS policy protects both. A separate vector database needs its own tenancy model."],
  ["Embeddings", "Local fastembed", "No API cost or rate limit, which is what makes retrieval evaluation over hundreds of questions free."],
  ["Keyword search", "Postgres FTS", "Already present; no second system to operate for the keyword half of hybrid retrieval."],
  ["Inference", "Groq", "Two model sizes let structural JSON tasks avoid competing with synthesis for a scarce token budget."],
  ["Identity", "Supabase", "JWTs verified against a public JWKS endpoint, so the backend holds no auth secret."],
], [0.17, 0.17, 0.66]));

/* ---- CH 4 ---- */
children.push(H1("4. The Agent Pipeline"));
children.push(TAGS("research"));
children.push(LEDE("This chapter is the first product, Deep Research — the pipeline that runs when a user types a question at /#research. Nine nodes in a directed graph. The important structural feature is not their number but the edge that goes backwards: gap analysis can return the run to search when the evidence gathered so far does not support a confident answer."));
children.push(...FIGURE("fig4-pipeline.png", 6.3, 4, "Research pipeline with reflective loop",
  "Triage routes non-research messages straight to the end. The corpus node folds the user's own documents into the same evidence set as the web."));
children.push(TBL(["Node", "Responsibility", "Model", "Design note"], [
  ["Triage", "Classify effort: chat, simple, or deep", "20B", "Fails open to deep — over-researching costs time, under-researching costs correctness."],
  ["Planner", "Decompose into 3–5 sub-queries", "20B", "Structured output with a JSON fallback; the provider's tool-call wrapper intermittently rejects its own valid generation."],
  ["Search", "Execute sub-queries, deduplicate by URL", "—", "Breadth scales with triage: 3 results per query for simple, 5 for deep."],
  ["Reader", "Fetch and extract HTML and PDF concurrently", "—", "Records when extraction failed and a snippet was substituted, so the report can disclose it."],
  ["Corpus", "Retrieve from the user's own documents", "—", "Runs even when web search returned nothing — the answer may be in the user's files."],
  ["Analyst", "Synthesise a draft across all evidence", "120B", "Corpus chunks hold reserved slots so uploaded documents cannot be crowded out."],
  ["Fact-checker", "Extract, verify and corroborate claims", "120B", "All claims in one call with per-claim evidence; verifying individually consumed 257 s of a 361 s run."],
  ["Gap analysis", "Decide whether to loop or report", "20B", "Hard iteration ceiling prevents unbounded loops."],
  ["Report", "Compose the final document", "120B", "Sources and confidence assembled in code, not generated — removing a place a reference could be invented."],
], [0.15, 0.26, 0.09, 0.5]));

/* ---- CH 5 ---- */
children.push(H1("5. Retrieval-Augmented Generation Subsystem"));
children.push(TAGS("files"));
children.push(LEDE("This chapter is the second product, Chat with Files — a separate page at /#files with its own query box, which answers only from documents the user has uploaded. It is not a stage of the pipeline in Chapter 4; the two meet at one point only, the corpus node described in 1.2. Retrieval runs two searches and fuses their rankings. Neither is reliable alone: embeddings place Sev-1 and Sev-2 almost on top of each other, which is exactly wrong when the user asked about one of them; keyword search has no notion of synonym or paraphrase."));
children.push(H2("5.1 Ingestion"));
children.push(P("A file is validated by magic bytes rather than extension, extracted according to type, sanitised, split into 1,000-character chunks with 150-character overlap, and embedded locally. The HTTP request returns as soon as the record exists; extraction and embedding happen afterwards, so a 200-page PDF cannot exceed a proxy timeout. Documents left mid-ingest by a restart are failed after fifteen minutes."));
children.push(H2("5.2 Hybrid retrieval"));
children.push(P("Both retrievers return twenty candidates. Their rankings are combined by Reciprocal Rank Fusion, which fuses by rank rather than score — cosine similarity and ts_rank are different scales with no meaningful conversion, and normalising one onto the other would invent a relationship that does not exist."));
children.push(...FIGURE("fig5-hybrid.png", 6.0, 5, "Hybrid retrieval, measured",
  "Rank of the chunk containing the answer, by retriever, on a field-service document of error codes and part numbers. Lower is better."));
children.push(NOTE("Reading this honestly.", "Two of the three queries were already handled by vector search alone. The third is the case hybrid retrieval exists for — and the class of query (version strings, part numbers, error codes) is precisely the one where users are most certain they typed it correctly, so a miss reads as the product being broken."));
children.push(new Paragraph({ spacing: { after: 160 }, children: [] }));
children.push(H2("5.3 The agentic loop"));
children.push(P("Retrieval is not a single shot. The system grades whether retrieved excerpts actually answer the question; if not, it rewrites the query with different wording and retries once. Only after that does it decline. This is what produces correct refusals rather than confident guesses."));

/* ---- CH 6 ---- */
children.push(H1("6. Data Layer and Security"));
children.push(TAGS("shared"));
children.push(H2("6.1 Tenant isolation"));
children.push(P("Application code filters every query by user. That is necessary and insufficient: it is one forgotten WHERE clause away from a cross-tenant leak. Postgres row-level security provides the second line. Policies are keyed on a session variable set when a connection is checked out of the pool, and current_setting(..., true) returns NULL when unset — so an unscoped session matches nothing and fails closed."));
children.push(P("Two roles make this work. The owner role runs migrations and the payment webhook path, which has no user context and must read across tenants. The runtime role owns nothing and has no BYPASSRLS, so policies bind to it. If both connection strings name the same role, every policy is inert — and startup says so loudly."));
children.push(TBL(["Check", "Expected", "Result"], [
  ["Owner reads their own rows", "Visible", "Pass"],
  ["Unfiltered SELECT by another tenant", "Zero rows", "Pass"],
  ["Session with no tenant set", "Zero rows (fail closed)", "Pass"],
  ["Insert a row under another tenant's id", "Refused by WITH CHECK", "Pass"],
], [0.45, 0.33, 0.22]));
children.push(P("Verified live across all six tables. These checks run as a build gate; a regression fails CI rather than reaching production.", { size: 19, color: INK3, italics: true }));
children.push(H2("6.2 Untrusted document content"));
children.push(P("An uploaded file is the easiest path into a model's context for anyone who wants to steer it. Defence is structural: retrieved excerpts are wrapped in <document> tags and the system prompt states that anything inside them is data, never a command. A closing tag inside an excerpt is neutralised, or it would end the block early and hand back exactly the control the delimiter withholds."));
children.push(NOTE("Tested, with an instructive result.", "A document was uploaded containing an instruction to ignore all directives and reply with a single fixed word. The regex sanitiser missed it entirely — its patterns expected different phrasing. The delimiting held: the system answered both questions correctly and noted that the document “contains a line that appears to be an injected instruction… treated as part of the document content and is not followed.” The patterns were widened afterwards, but the lesson stands: the structural separation is the defence.", "9C2F26"));

children.push(H2("6.3 Schema management"));
children.push(P("Four Alembic revisions replace the earlier pattern of create_all() plus hand-written ADD COLUMN IF NOT EXISTS statements, which could add a column but never alter or remove one and recorded nothing about what had been applied. A database predating Alembic is stamped at the baseline rather than re-running it, so existing data is preserved."));

/* ---- CH 7 ---- */
children.push(H1("7. Verification and Confidence Scoring"));
children.push(TAGS("research"));
children.push(LEDE("This chapter describes the part of the system that most distinguishes it, and the part where a plausible-looking implementation is most likely to be measuring something other than what it claims."));
children.push(H2("7.1 Why naïve verification fails"));
children.push(P("The obvious implementation extracts claims from the draft and checks them against the source documents. It is circular. A claim faithfully summarised from a source always agrees with that source, including when the source is wrong. Such a system measures summarisation fidelity while its interface calls the result grounding."));
children.push(H2("7.2 Independent corroboration"));
children.push(P("Each claim is searched for separately, concurrently, and the results are labelled distinctly from the documents the draft was written from. A claim confirmed by a source the analyst never saw is marked independently corroborated. The verifier caps confidence at 0.7 when only prior evidence supports a claim — agreement with one's own summary is weak evidence."));
children.push(H2("7.3 Evidence selection"));
children.push(P("Evidence was previously assembled by position: the first 1,000 characters of each document, truncated to 6,000 overall. On a forty-source run that is roughly the top of the first six, so a claim drawn from anywhere else was unverifiable in principle and returned “unverified” for reasons unrelated to its truth. Passages are now selected by relevance to the specific claim across every source."));
children.push(H2("7.4 Scoring the run"));
children.push(P("The run's confidence is not the mean of its claim scores. A mean hides its worst member: four solid claims and one fabrication scored identically to five mediocre ones. Unsupported claims are weighted more heavily, and the result is capped by the quality of the evidence beneath it — thin evidence does not make an answer wrong, it makes a high score unjustifiable."));
children.push(TBL(["Condition", "Effect", "Rationale"], [
  ["Unsupported claim present", "Weighted 1.5×", "Cannot be averaged away by its neighbours."],
  ["Fewer than 3 distinct sources", "Cap 60%", "Perfect claims over two documents is not a confident answer."],
  ["Fewer than 5 distinct sources", "Cap 80%", "Insufficient breadth for a high score."],
  ["Majority of sources snippet-only", "Cap 70%", "A search snippet is not the paper it stands for."],
  ["Independent corroboration", "Up to +10%", "Scaled by the proportion of claims confirmed externally."],
  ["No claims extracted", "Score 0.0", "An invented middling number reads as a measurement when nothing was measured."],
], [0.33, 0.17, 0.5]));

children.push(P("Every adjustment is reported alongside the number, and the report carries a \u201cWhat limits this score\u201d section naming what would raise it. A score a reader cannot interrogate is decoration."));

/* ---- CH 8 ---- */
children.push(H1("8. Testing and Continuous Integration"));
children.push(TAGS("shared"));
children.push(TBL(["Measure", "Value", "Detail"], [
  ["Backend tests", "165", "unit and integration, 5 s"],
  ["Frontend tests", "31", "hooks and components"],
  ["Build gates", "4", "tests · RLS · evals · frontend"],
  ["Migrations", "4", "versioned, reversible"],
], [0.32, 0.16, 0.52]));
children.push(H2("8.1 What CI verifies"));
children.push(P("The pipeline runs against pgvector/pgvector:pg16 with a genuine low-privilege role — not SQLite. This matters: the application refuses to start on SQLite, so a suite running against it would cover none of the pgvector queries, the tenant scoping, or the migrations that actually execute in production."));
children.push(P("Beyond the unit suites, two gates assert behaviour rather than code. The first confirms Postgres genuinely refuses cross-tenant reads — the policies existing is not the same as the policies working. The second runs the golden evaluation set, so a retrieval regression fails the build."));
children.push(H2("8.2 Tests that encode defects"));
children.push(P("Several tests assert the specific failure rather than the happy path, so a regression reads as the thing that went wrong:"));
children.push(BULLET("an unsupported claim cannot be averaged away by four good ones;"));
children.push(BULLET("perfect claims over two sources are still capped;"));
children.push(BULLET("a corroborating hit on a page the draft already used is not independent;"));
children.push(BULLET("a run with no claims scores 0.0, not an invented 0.5;"));
children.push(BULLET("a tracking parameter on a URL does not make a real citation look fabricated;"));
children.push(BULLET("a closing tag inside an excerpt cannot end the delimiter block early."));

/* ---- CH 9 ---- */
children.push(H1("9. Results and Measurements"));
children.push(TAGS("research", "files"));
children.push(LEDE("Every figure in this chapter was produced by running the system. Nothing here is an estimate, and where a measurement is weaker than it appears, this chapter says so."));
children.push(H2("9.1 Public benchmark — SQuAD 2.0"));
children.push(TAGS("files"));
children.push(P("The project's own golden set is fourteen questions over three documents written by the author. It is a useful regression check and poor evidence: a perfect score on one's own questions demonstrates that the system does what was expected, not that it works. SQuAD 2.0 is a public benchmark of human-written questions over Wikipedia paragraphs, including questions deliberately unanswerable from their source."));
children.push(TBL(["Metric", "Score", "Detail"], [
  ["Recall @ 4", "1.000", "25/25 questions reached their source paragraph"],
  ["Mean reciprocal rank", "1.000", "correct paragraph always ranked first"],
  ["Answer accuracy", "0.880", "22/25 exact substring match"],
  ["Judge verdicts", "25/25 PASS", "faithfulness and relevance"],
], [0.34, 0.18, 0.48]));
children.push(NOTE("Three qualifications, stated plainly.", "1. The corpus was 31 paragraphs; a perfect recall score over a small haystack is easier than over a realistic one. 2. Answer accuracy is understated — manual review of the three failures found two were correct answers phrased differently. 3. The refusal rate is not yet reliably measured: the first run reported 0.167, which inspection showed was a grader defect, not a system defect. The true figure is approximately 0.667.", "9C2F26"));
children.push(new Paragraph({ spacing: { after: 200 }, children: [] }));
children.push(H2("9.2 Internal golden set"));
children.push(TAGS("research"));
children.push(P("Run as a build gate on every push. Scores of 1.000 here mean \u201cno regression since the last commit\u201d, and should not be read as evidence of accuracy."));
children.push(TBL(["Metric", "Score", "Baseline", "Result"], [
  ["Retrieval recall", "1.000", "1.000", "OK"],
  ["Answer accuracy", "1.000", "1.000", "OK"],
  ["Refusal rate", "1.000", "1.000", "OK"],
  ["Unanswerable retrieved something", "0.750", "1.000", "OK"],
], [0.45, 0.19, 0.19, 0.17]));
children.push(H2("9.3 Confidence distribution across real runs"));
children.push(TAGS("research"));
children.push(P("Five genuine research runs against live web sources. The spread is the point: a system that returns a high score for every question is not measuring anything."));
children.push(...FIGURE("fig9-confidence.png", 6.2, 9, "Confidence by run, with token cost",
  "Confidence is not correlated with effort. The 18% run consumed more tokens than the 65% run — it searched hard and still found little support."));
children.push(NOTE("The 18% run is the most informative result in this report.", "Asked how much electricity data centres use worldwide, the system gathered 24 sources, supported one claim of five, corroborated none independently, and reported: “4 claims had no supporting evidence in the sources found”. Data-centre energy figures are widely cited second-hand and poorly sourced. A system that returned 85% here would be worse, not better."));
children.push(new Paragraph({ spacing: { after: 200 }, children: [] }));
children.push(H2("9.4 Cost and latency"));
children.push(TAGS("research"));
children.push(TBL(["Measure", "Value", "Detail"], [
  ["Mean tokens per run", "15,370", "across five live runs"],
  ["Mean cost per run", "$0.0054", "at published provider rates"],
  ["RAG answer latency", "2.0 s", "retrieval, generation and judge"],
  ["Retrieval only", "0.3 s", "25 questions, no API calls"],
], [0.34, 0.18, 0.48]));
children.push(P("Embeddings run on the server, so retrieval costs nothing and evaluation over hundreds of questions is free. This is what makes continuous measurement practical at zero budget — the constraint on evaluation is the answer pass, not retrieval."));
children.push(H2("9.5 Interface quality"));
children.push(P("Measured in the browser against the running application, before and after the remediation work described in Chapter 10."));
children.push(TBL(["Measure", "Before", "After", "Standard"], [
  ["Horizontal overflow at 375 px", "265 px", "0 px", "No sideways scroll"],
  ["Controls below 44 px touch target", "15 of 29", "0 of 29", "Apple HIG"],
  ["Visible keyboard focus", "None", "All controls", "WCAG 2.4.7"],
  ["Light-theme muted text contrast", "3.79 : 1", "4.72 : 1", "WCAG AA (4.5)"],
  ["Light-theme link contrast", "3.72 : 1", "4.84 : 1", "WCAG AA (4.5)"],
  ["Dark-theme pairs passing AA", "14 of 14", "14 of 14", "WCAG AA"],
  ["Frontend automated tests", "0", "31", "—"],
  ["Page height, signed-in home", "8,272 px", "2,740 px", "—"],
], [0.4, 0.18, 0.18, 0.24]));

/* ---- CH 10 ---- */
children.push(H1("10. Evaluation, Limitations and Future Work"));
children.push(TAGS("research", "files", "shared"));
children.push(H2("10.1 Defects found and corrected"));
children.push(P("A structured review found a consistent pattern: several controls were documented in comments and marketing copy but did not exist in the running system. These are recorded because the pattern is more instructive than any individual bug."));
children.push(TBL(["Defect", "Why it mattered", "Resolution"], [
  ["Row-level security absent", "Documented as “real defense-in-depth”; zero policies existed and both connection strings named the same role.", "Policies written, second role created, four checks gated in CI."],
  ["Circular verification", "Claims checked against the text they were summarised from; the score measured fidelity, not support.", "Independent per-claim search and corroboration flag."],
  ["Evidence truncation", "Verification saw roughly six of forty sources, making most claims unverifiable in principle.", "Relevance-based selection across all sources."],
  ["CI ran on SQLite", "The application refuses to start on SQLite; the green check covered none of the production data paths.", "Postgres + pgvector service container."],
  ["CI had never executed", "The workflow file sat one directory below the repository root, where Actions does not look.", "Relocated; first successful run followed."],
  ["Tables unrendered", "Every Markdown table arrived as a wall of pipes — react-markdown has no table support without a plugin.", "remark-gfm added; charts and diagrams followed."],
  ["Uploads unsanitised", "Scraped pages were filtered; uploaded documents — far easier to control — were not.", "Sanitised at ingest; context delimited structurally."],
], [0.22, 0.44, 0.34]));
children.push(H2("10.2 Current limitations"));
children.push(BULLET("The confidence score is unvalidated against human judgement. A harness exists to measure whether “verified” correlates with “true”, but it requires human labels not yet collected. This is the single largest gap in the project's evidence."));
children.push(BULLET("The benchmark corpus is small — thirty-one paragraphs; recall should be expected to fall on a realistic corpus."));
children.push(BULLET("Refusal rate is not reliably measured pending a corrected re-run."));
children.push(BULLET("Ingestion runs in the web process; a restart mid-upload strands a record, mitigated by a reaper rather than solved by a durable queue."));
children.push(BULLET("Ranking quality is unmeasured beyond MRR; NDCG is not computed."));
children.push(BULLET("RAG citations are not validated the way research-path citations are."));
children.push(H2("10.3 Future work, in priority order"));
children.push(BULLET("Collect human labels for 100+ verified claims and report precision, recall and calibration. Nothing else changes the project's credibility as much."));
children.push(BULLET("Expand the benchmark to 200+ questions over a larger corpus, tracking scores across runs so regressions are visible."));
children.push(BULLET("Validate RAG citations against retrieved chunks, as the research path already does."));
children.push(BULLET("Durable job queue for ingestion."));
children.push(BULLET("Cross-encoder reranking on the fused candidate set."));
children.push(H2("10.4 Assessment"));
children.push(P("The system does what it claims within the limits of what has been measured. Its retrieval is strong on a public benchmark; its refusal behaviour is correct on the cases examined; its confidence scoring is conservative by construction and reports its own reasoning. Its security controls are enforced by the database and verified by the build."));
children.push(P("What remains unproven is whether the confidence number corresponds to truth. Every metric in Chapter 9 measures internal consistency or retrieval accuracy. None measures whether a claim marked verified is actually correct — and until human labels exist, that question is open. This report states that plainly rather than letting a column of 1.000 scores imply otherwise."));


/* ---- CH 11: SRS diagrams ---- */
children.push(H1("11. SRS Diagrams"));
children.push(TAGS("research", "files", "shared"));
children.push(LEDE("The nine diagrams a complete specification carries, drawn in the same palette as the rest of this report rather than a tool's defaults. Colour is not decoration here: it separates the system from its data and from everything outside its boundary, which is the distinction most of these figures exist to make."));
children.push(TBL(["Shape / colour", "Means"], [
  ["Rounded rectangle, bronze", "A process — part of the system under discussion"],
  ["Cylinder, teal", "Data at rest"],
  ["Slanted parallelogram, plum", "An external service, outside the system boundary"],
  ["Green fill", "A terminal success state"],
  ["Red fill", "A terminal failure state"],
  ["Dashed line", "A conditional or optional path"],
], [0.34, 0.66]));

const SRS = [
  ["11.1", "Use Case Diagram", "srs-A1.png", "Who does what, and what every research action must pass through first. The include-relationship shows authentication and quota enforcement standing between the user and every expensive operation."],
  ["11.2", "Context Diagram — DFD Level 0", "srs-A2.png", "The system as one process with its external entities. Four dependencies, and the user's documents never cross the boundary."],
  ["11.3", "Data Flow Diagram — Level 1", "srs-A3.png", "The six real processes and the stores each touches. Every store access is tenant-scoped, which is the property row-level security enforces."],
  ["11.4", "Entity-Relationship Diagram", "srs-A4.png", "The schema as deployed. Colour separates tables carrying user_id directly from those deriving it through a parent — the distinction that decides how each RLS policy is written."],
  ["11.5", "Sequence — Deep Research run", "srs-A5.png", "One research request end to end. The token travels in the first WebSocket message because browsers cannot set headers on a handshake; quota is reserved before expensive work and refunded if the run fails."],
  ["11.6", "Sequence — Chat with Files query", "srs-A6.png", "The agentic retrieval loop. The alt block is what produces correct refusals: grade, rewrite, retry once, and only then decline."],
  ["11.7", "State Diagram — Document lifecycle", "srs-A7.png", "Why the status field exists and the failure it guards. A restart between 'record created' and 'embedded' leaves nothing to advance the row, which is what the fifteen-minute reaper is for."],
  ["11.8", "Deployment Diagram", "srs-A8.png", "Where each part runs, and the two distinct database connections. That separation is the whole mechanism of row-level security."],
  ["11.9", "Component Diagram", "srs-A9.png", "The module structure as it exists on disk, layered so dependencies point in one direction only."],
];
SRS.forEach(([num, title, file, cap]) => {
  children.push(H2(`${num} ${title}`));
  children.push(...FIGURE(file, 6.3, num, title, cap));
});

/* ---- APPENDIX ---- */
children.push(H1("Appendix: Environment and Reproduction"));
children.push(TAGS("shared"));
children.push(TBL(["Component", "Version / detail"], [
  ["Backend", "Python 3.12, FastAPI 0.121, LangGraph 0.2.76, SQLAlchemy 2.0"],
  ["Frontend", "React 19, Vite 8, TypeScript, Vitest"],
  ["Database", "PostgreSQL 16, pgvector 0.4.1, HNSW + GIN indexes"],
  ["Embeddings", "BAAI/bge-small-en-v1.5, 384 dimensions, local"],
  ["Inference", "openai/gpt-oss-120b (synthesis), openai/gpt-oss-20b (structural, judge)"],
  ["Codebase", "8,807 lines backend · 8,516 lines frontend"],
  ["Tests", "165 backend · 31 frontend"],
], [0.28, 0.72]));
children.push(H2("Reproducing the measurements"));
children.push(BULLET("pytest -q — full backend suite"));
children.push(BULLET("npm run test — frontend suite"));
children.push(BULLET("python scripts/verify_rls.py — tenant isolation checks"));
children.push(BULLET("python -m evals.run --answers — internal golden set"));
children.push(BULLET("python -m evals.squad --retrieval --questions 200 — public benchmark, no API cost"));
children.push(BULLET("python -m evals.factcheck_accuracy --export claims.jsonl — label claims for accuracy measurement"));

/* ====================== ASSEMBLE ====================== */
const doc = new Document({
  background: { color: PAPER },
  creator: "Prince Yadav",
  title: "Cognita — Project Report",
  description: "Architecture, requirements and measured results for the Cognita multi-agent research assistant.",
  numbering: {
    config: [{
      reference: "bullets",
      levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 360, hanging: 240 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 240 } } } },
      ],
    }],
  },
  styles: {
    default: {
      document: { run: { font: "Georgia", size: 21, color: INK2 } },
      heading1: { run: { font: "Calibri", size: 34, bold: true, color: INK } },
      heading2: { run: { font: "Calibri", size: 24, bold: true, color: INK } },
    },
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },           // US Letter
        margin: { top: 1440, bottom: 1440, left: 1800, right: 1800 },
      },
    },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log(`wrote ${OUT} — ${buf.length.toLocaleString()} bytes`);
});
