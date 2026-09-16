/**
 * Build the technical appendix as a .docx.
 *
 * Prompts and figure sources are long preformatted blocks, so they get a
 * monospace paragraph on a tinted ground rather than a table — a table cell
 * with 40 lines of text paginates badly in Word.
 */
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  PageBreak, TableOfContents, Bookmark, InternalHyperlink, convertInchesToTwip,
} = require("docx");

const ROWS = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const FIGS = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const OUT = process.argv[4];

const INK = "16150F", INK2 = "474338", INK3 = "7C7566";
const BRONZE = "A06B21", TEAL = "1D5F63", RULE = "DDD6C8", PAPER2 = "FAF7F1", CODEBG = "FBFAF6";
const PAGE_W = convertInchesToTwip(8.5) - convertInchesToTwip(1.25) * 2;

const SECTIONS = [
  "Part A — Prompt Catalogue",
  "Part B — Figure Specifications",
  "Part C — Rendering the Figures",
];
const anchorFor = (t) => "sec" + SECTIONS.indexOf(t);

const P = (text, o = {}) => new Paragraph({
  spacing: { after: o.after ?? 140, line: 300 },
  children: [new TextRun({
    text, font: o.font ?? "Georgia", size: o.size ?? 21,
    color: o.color ?? INK2, bold: o.bold, italics: o.italics,
  })],
});

const H1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1, pageBreakBefore: true,
  spacing: { before: 240, after: 200 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: INK, space: 6 } },
  children: [new Bookmark({
    id: anchorFor(text),
    children: [new TextRun({ text, font: "Calibri", size: 32, bold: true, color: INK })],
  })],
});

const H2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2, spacing: { before: 300, after: 100 },
  keepNext: true,
  children: [new TextRun({ text, font: "Calibri", size: 23, bold: true, color: INK })],
});

/** Preformatted block: one paragraph per line so Word wraps nothing, on a
 *  tinted single-cell table so the block reads as a unit. */
function CODE(text) {
  const lines = text.replace(/\r/g, "").split("\n");
  return new Table({
    width: { size: PAGE_W, type: WidthType.DXA },
    columnWidths: [PAGE_W],
    borders: {
      top: { style: BorderStyle.SINGLE, size: 3, color: RULE },
      bottom: { style: BorderStyle.SINGLE, size: 3, color: RULE },
      left: { style: BorderStyle.SINGLE, size: 3, color: RULE },
      right: { style: BorderStyle.SINGLE, size: 3, color: RULE },
      insideHorizontal: { style: BorderStyle.NONE },
      insideVertical: { style: BorderStyle.NONE },
    },
    rows: [new TableRow({
      children: [new TableCell({
        width: { size: PAGE_W, type: WidthType.DXA },
        shading: { type: ShadingType.CLEAR, fill: CODEBG },
        margins: { top: 140, bottom: 140, left: 180, right: 180 },
        children: lines.map((l) => new Paragraph({
          spacing: { after: 0, line: 230 },
          children: [new TextRun({
            // A space keeps an empty line from collapsing to nothing.
            text: l.length ? l : " ",
            font: "Consolas", size: 15, color: INK2,
          })],
        })),
      })],
    })],
  });
}

/** Metadata strip above a prompt or figure. */
function META(left, tags, tone = BRONZE) {
  return new Table({
    width: { size: PAGE_W, type: WidthType.DXA },
    columnWidths: [Math.round(PAGE_W * 0.52), Math.round(PAGE_W * 0.48)],
    borders: {
      top: { style: BorderStyle.SINGLE, size: 3, color: RULE },
      bottom: { style: BorderStyle.NONE },
      left: { style: BorderStyle.SINGLE, size: 3, color: RULE },
      right: { style: BorderStyle.SINGLE, size: 3, color: RULE },
      insideHorizontal: { style: BorderStyle.NONE },
      insideVertical: { style: BorderStyle.NONE },
    },
    rows: [new TableRow({
      children: [
        new TableCell({
          width: { size: Math.round(PAGE_W * 0.52), type: WidthType.DXA },
          shading: { type: ShadingType.CLEAR, fill: PAPER2 },
          margins: { top: 120, bottom: 120, left: 180, right: 100 },
          children: [new Paragraph({ spacing: { after: 0 }, children: [
            new TextRun({ text: left.id + "   ", font: "Consolas", size: 15, color: tone }),
            new TextRun({ text: left.title, font: "Calibri", size: 21, bold: true, color: INK }),
          ] })],
        }),
        new TableCell({
          width: { size: Math.round(PAGE_W * 0.48), type: WidthType.DXA },
          shading: { type: ShadingType.CLEAR, fill: PAPER2 },
          margins: { top: 120, bottom: 120, left: 100, right: 180 },
          children: [new Paragraph({
            spacing: { after: 0 }, alignment: AlignmentType.RIGHT,
            children: [new TextRun({ text: tags, font: "Consolas", size: 14, color: TEAL })],
          })],
        }),
      ],
    })],
  });
}

/** The prose that sits between the metadata strip and the code block. */
function WHY(text) {
  return new Table({
    width: { size: PAGE_W, type: WidthType.DXA },
    columnWidths: [PAGE_W],
    borders: {
      top: { style: BorderStyle.NONE },
      bottom: { style: BorderStyle.SINGLE, size: 3, color: RULE },
      left: { style: BorderStyle.SINGLE, size: 3, color: RULE },
      right: { style: BorderStyle.SINGLE, size: 3, color: RULE },
      insideHorizontal: { style: BorderStyle.NONE },
      insideVertical: { style: BorderStyle.NONE },
    },
    rows: [new TableRow({
      children: [new TableCell({
        width: { size: PAGE_W, type: WidthType.DXA },
        shading: { type: ShadingType.CLEAR, fill: "FFFFFF" },
        margins: { top: 130, bottom: 130, left: 180, right: 180 },
        children: [new Paragraph({
          spacing: { after: 0, line: 280 },
          children: [new TextRun({ text, font: "Georgia", size: 19, color: INK2 })],
        })],
      })],
    })],
  });
}

/** Key/value specification block for a figure. */
function SPEC(pairs) {
  const kw = Math.round(PAGE_W * 0.16), vw = PAGE_W - kw;
  return new Table({
    width: { size: PAGE_W, type: WidthType.DXA },
    columnWidths: [kw, vw],
    borders: {
      top: { style: BorderStyle.NONE },
      bottom: { style: BorderStyle.SINGLE, size: 3, color: RULE },
      left: { style: BorderStyle.SINGLE, size: 3, color: RULE },
      right: { style: BorderStyle.SINGLE, size: 3, color: RULE },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: "F0EBE0" },
      insideVertical: { style: BorderStyle.NONE },
    },
    rows: pairs.map(([k, v]) => new TableRow({
      children: [
        new TableCell({
          width: { size: kw, type: WidthType.DXA },
          margins: { top: 110, bottom: 110, left: 180, right: 80 },
          children: [new Paragraph({ spacing: { after: 0 }, children: [
            new TextRun({ text: k, font: "Consolas", size: 14, color: INK3, allCaps: true }),
          ] })],
        }),
        new TableCell({
          width: { size: vw, type: WidthType.DXA },
          margins: { top: 110, bottom: 110, left: 80, right: 180 },
          children: [new Paragraph({ spacing: { after: 0, line: 270 }, children: [
            new TextRun({ text: v, font: "Georgia", size: 19, color: INK2 }),
          ] })],
        }),
      ],
    })),
  });
}

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
      margins: { top: 150, bottom: 150, left: 200, right: 200 },
      children: [new Paragraph({ spacing: { after: 0, line: 285 }, children: [
        new TextRun({ text: label + " ", font: "Calibri", size: 20, bold: true, color: tone }),
        new TextRun({ text, font: "Georgia", size: 20, color: INK2 }),
      ] })],
    })],
  })],
});

const GAP = (n = 180) => new Paragraph({ spacing: { after: n }, children: [] });

/* ====================== DOCUMENT ====================== */
const children = [];

children.push(
  new Paragraph({ spacing: { before: 1500, after: 200 }, children: [new TextRun({
    text: "TECHNICAL APPENDIX · COMPANION TO THE PROJECT REPORT",
    font: "Consolas", size: 15, color: BRONZE, characterSpacing: 40 })] }),
  new Paragraph({ spacing: { after: 140 }, children: [new TextRun({
    text: "Prompts and", font: "Calibri", size: 64, bold: true, color: INK })] }),
  new Paragraph({ spacing: { after: 320 }, children: [new TextRun({
    text: "figure specifications", font: "Georgia", size: 56, italics: true, color: BRONZE })] }),
  new Paragraph({ spacing: { after: 480, line: 320 }, children: [new TextRun({
    text: "Every instruction the system sends to a model, reproduced verbatim from source, and complete specifications for the SRS figures — each with renderable source so the diagrams can be regenerated rather than redrawn.",
    font: "Georgia", size: 23, color: INK2 })] }),
);

children.push(
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ spacing: { after: 240 }, children: [new TextRun({
    text: "CONTENTS", font: "Calibri", size: 26, bold: true, color: INK })] }),
  ...SECTIONS.map((title) => new Paragraph({
    spacing: { after: 110, line: 280 },
    children: [new InternalHyperlink({
      anchor: anchorFor(title),
      children: [new TextRun({ text: title, font: "Georgia", size: 21, color: INK2 })],
    })],
  })),
);

/* ---- Part A ---- */
children.push(H1(SECTIONS[0]));
children.push(P("These are extracted from the source files, not retyped, so this document cannot drift from what the system actually sends. Each entry records the model it goes to, the temperature it runs at, and why it is worded the way it is."));
children.push(NOTE("Why temperature varies.", "Classification and verification run at 0.0 because the same input should give the same verdict — a fact-checker that disagrees with itself between runs is not a fact-checker. Synthesis runs at 0.2–0.3, low enough to stay close to the sources and high enough not to produce stilted prose."));
children.push(GAP());

ROWS.forEach((r, i) => {
  children.push(H2(`A${String(i + 1).padStart(2, "0")}. ${r.role}`));
  children.push(META({ id: `A${String(i + 1).padStart(2, "0")}`, title: r.role },
    `${r.model} · temp ${r.temp}`));
  children.push(WHY(r.note));
  children.push(WHY(`${r.file} · ${r.name} · ${r.chars} characters`));
  children.push(CODE(r.text));
  children.push(GAP(220));
});

/* ---- Part B ---- */
children.push(H1(SECTIONS[1]));
children.push(P("Nine figures a complete SRS would carry. Each specification states what the figure must show and why it earns its place, then gives source a tool renders directly — so the diagram can be regenerated when the system changes rather than redrawn by hand and slowly going stale."));
children.push(NOTE("Mermaid rather than an image format.", "A diagram checked in as text can be diffed, reviewed and corrected in a pull request. A PNG cannot, which is how architecture diagrams end up describing a system that no longer exists."));
children.push(GAP());

FIGS.forEach((f) => {
  children.push(H2(`Figure ${f.id} — ${f.title}`));
  children.push(META({ id: f.id, title: f.title }, "mermaid · renderable"));
  children.push(SPEC([
    ["Purpose", f.purpose],
    ["Actors", f.actors],
    ["Elements", f.elements],
    ["Layout", f.layout],
  ]));
  children.push(CODE(f.src));
  children.push(GAP(220));
});

/* ---- Part C ---- */
children.push(H1(SECTIONS[2]));
children.push(H2("In a document"));
children.push(P("GitHub, GitLab, Notion and Obsidian render Mermaid from a fenced block labelled mermaid. Paste the source between the fences and it draws on save — no toolchain."));
children.push(H2("As image files"));
children.push(P("For Word or LaTeX, render to SVG or PNG with the Mermaid CLI:"));
children.push(CODE(`npm install -g @mermaid-js/mermaid-cli
mmdc -i figure-a1.mmd -o figure-a1.svg -b transparent
mmdc -i figure-a1.mmd -o figure-a1.png -s 2   # 2x for print`));
children.push(GAP(140));
children.push(P("Use SVG wherever the target supports it. The project report's own figures were rasterised at 2× only because no SVG renderer was available on the build machine; at 1× they would be visibly soft in print."));
children.push(H2("Without installing anything"));
children.push(P("mermaid.live renders pasted source in the browser and exports SVG or PNG directly. Adequate for a one-off; the CLI is better once the diagrams are checked in, because it can regenerate all of them in a single command when the system changes."));
children.push(H2("Keeping them honest"));
children.push(P("Each specification above names what the figure must show. When the system changes, update the source and re-render — and if the change contradicts the Purpose line, the figure has stopped earning its place and should be rethought rather than patched."));

const doc = new Document({
  creator: "Prince Yadav",
  title: "Cognita — Technical Appendix",
  description: "Prompt catalogue and SRS figure specifications for the Cognita research assistant.",
  styles: {
    default: {
      document: { run: { font: "Georgia", size: 21, color: INK2 } },
      heading1: { run: { font: "Calibri", size: 32, bold: true, color: INK } },
      heading2: { run: { font: "Calibri", size: 23, bold: true, color: INK } },
    },
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, bottom: 1440, left: 1800, right: 1800 },
      },
    },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log(`wrote ${OUT} — ${buf.length.toLocaleString()} bytes, ${ROWS.length} prompts, ${FIGS.length} figures`);
});
