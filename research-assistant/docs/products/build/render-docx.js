/**
 * Build one per-product report as a .docx from the JSON the HTML render emits.
 *
 *   node render-docx.js <payload.json> <figures-dir> <out.docx>
 *
 * Both formats therefore carry the same words. No Word TOC field is used — see
 * the README for why — so the document opens without a dialog.
 */
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  ImageRun, PageBreak, LevelFormat, convertInchesToTwip,
  Bookmark, InternalHyperlink,
} = require("docx");

const [PAYLOAD, FIGDIR, OUT] = process.argv.slice(2);
const D = JSON.parse(fs.readFileSync(PAYLOAD, "utf8"));
const META = D.meta;

/* ---- Cognita's own light theme, token for token from frontend/src/index.css.
   One palette for both reports: the components and the accent have to mean the
   same thing in either document. ---- */
const C = {
  paper: "F0EEE6",        // --bg-app
  paper2: "F5F2EA",
  card: "FBFAF7",         // --bg-card
  rule: "E2DDD2",         // --card-edge, flattened
  ruleSoft: "EBE7DE",
  accent: "A94B2F",       // --accent
  accentDeep: "8F3D25",   // --accent-hover
  accentSoft: "F7EDE9",
  second: "1D5F63",
  secondSoft: "EAF1F1",
};
const INK = "141413", INK2 = "4D4C48", INK3 = "6B6965", BAD = "B3402F";
const PAGE_W = convertInchesToTwip(8.5) - convertInchesToTwip(1.25) * 2;

const WORDS = ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
               "Nine", "Ten", "Eleven", "Twelve"];

/* ---- helpers ---- */
const P = (text, o = {}) => new Paragraph({
  spacing: { after: o.after ?? 140, line: o.line ?? 300 },
  alignment: o.align,
  children: [new TextRun({
    text, font: o.font ?? "Georgia", size: o.size ?? 21,
    color: o.color ?? INK2, bold: o.bold, italics: o.italics,
  })],
});

const GAP = (h = 160) => new Paragraph({ spacing: { after: h }, children: [] });

const H1 = (text, anchor) => new Paragraph({
  heading: HeadingLevel.HEADING_1, pageBreakBefore: true,
  spacing: { before: 240, after: 80 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: INK, space: 6 } },
  children: [new Bookmark({
    id: anchor,
    children: [new TextRun({ text, font: "Calibri", size: 34, bold: true, color: INK })],
  })],
});

const CHAPNUM = (n) => new Paragraph({
  spacing: { before: 200, after: 40 },
  children: [new TextRun({
    text: `CHAPTER ${WORDS[n - 1].toUpperCase()}`, font: "Consolas", size: 14,
    color: C.accent, bold: true, characterSpacing: 40,
  })],
});

const H2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2, spacing: { before: 260, after: 120 },
  children: [new TextRun({ text, font: "Calibri", size: 24, bold: true, color: INK })],
});

const H3 = (text) => new Paragraph({
  spacing: { before: 200, after: 80 },
  children: [new TextRun({
    text: text.toUpperCase(), font: "Consolas", size: 15,
    color: INK3, characterSpacing: 30,
  })],
});

const LEDE = (text) => new Paragraph({
  spacing: { before: 120, after: 200, line: 320 },
  indent: { left: 240 },
  border: { left: { style: BorderStyle.SINGLE, size: 18, color: C.accent, space: 12 } },
  children: [new TextRun({ text, font: "Georgia", size: 23, color: INK })],
});

const BULLET = (text) => new Paragraph({
  numbering: { reference: "bullets", level: 0 },
  spacing: { after: 90, line: 280 },
  children: [new TextRun({ text, font: "Georgia", size: 21, color: INK2 })],
});

const CODE = (text) => new Table({
  width: { size: PAGE_W, type: WidthType.DXA }, columnWidths: [PAGE_W],
  borders: {
    top: { style: BorderStyle.SINGLE, size: 3, color: C.rule },
    bottom: { style: BorderStyle.SINGLE, size: 3, color: C.rule },
    left: { style: BorderStyle.SINGLE, size: 3, color: C.rule },
    right: { style: BorderStyle.SINGLE, size: 3, color: C.rule },
    insideHorizontal: { style: BorderStyle.NONE }, insideVertical: { style: BorderStyle.NONE },
  },
  rows: [new TableRow({ children: [new TableCell({
    width: { size: PAGE_W, type: WidthType.DXA },
    shading: { type: ShadingType.CLEAR, fill: C.paper2 },
    margins: { top: 140, bottom: 140, left: 180, right: 180 },
    children: String(text).split("\n").map((line) => new Paragraph({
      spacing: { after: 0, line: 240 },
      children: [new TextRun({ text: line || " ", font: "Consolas", size: 15, color: INK2 })],
    })),
  })] })],
});

const NOTE = (label, text, tone) => {
  const accent = tone === "bad" ? BAD
    : tone === "bronze" ? C.accent
    : C.second;
  const fill = tone === "bad" ? "FBF0EF" : C.secondSoft;
  return new Table({
    width: { size: PAGE_W, type: WidthType.DXA }, columnWidths: [PAGE_W],
    borders: {
      top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE },
      right: { style: BorderStyle.NONE }, insideHorizontal: { style: BorderStyle.NONE },
      insideVertical: { style: BorderStyle.NONE },
      left: { style: BorderStyle.SINGLE, size: 18, color: accent },
    },
    rows: [new TableRow({ children: [new TableCell({
      width: { size: PAGE_W, type: WidthType.DXA },
      shading: { type: ShadingType.CLEAR, fill },
      margins: { top: 160, bottom: 160, left: 200, right: 200 },
      children: [new Paragraph({ spacing: { after: 0, line: 290 }, children: [
        new TextRun({ text: label + " ", font: "Calibri", size: 20, bold: true, color: accent }),
        new TextRun({ text, font: "Georgia", size: 20, color: INK2 }),
      ] })],
    })] })],
  });
};

function TBL(headers, rows, widths) {
  const n = headers.length;
  const w = widths && widths.length === n ? widths : Array(n).fill(1 / n);
  const cols = w.map((x) => Math.round(PAGE_W * x));
  const cell = (text, opts) => new TableCell({
    width: { size: opts.w, type: WidthType.DXA },
    shading: { type: ShadingType.CLEAR, fill: opts.head ? C.paper2 : C.card },
    margins: { top: 90, bottom: 90, left: 120, right: 120 },
    children: [new Paragraph({
      spacing: { after: 0, line: 260 },
      children: [new TextRun({
        text: String(text),
        font: opts.first && !opts.head ? "Consolas" : "Calibri",
        size: opts.head ? 16 : (opts.first ? 16 : 18),
        bold: opts.head,
        color: opts.head ? INK3 : (opts.first ? INK : INK2),
        allCaps: opts.head,
      })],
    })],
  });
  const border = { style: BorderStyle.SINGLE, size: 4, color: C.rule };
  return new Table({
    width: { size: PAGE_W, type: WidthType.DXA }, columnWidths: cols,
    borders: {
      top: border, bottom: border, left: border, right: border,
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: C.rule },
      insideVertical: { style: BorderStyle.SINGLE, size: 2, color: C.rule },
    },
    rows: [
      new TableRow({ tableHeader: true,
        children: headers.map((h, i) => cell(h, { head: true, w: cols[i] })) }),
      ...rows.map((r) => new TableRow({
        children: r.map((c2, i) => cell(c2, { w: cols[i], first: i === 0 })),
      })),
    ],
  });
}

/** The big-number strip, as a one-row table. */
function STATS(items) {
  const cols = items.map(() => Math.round(PAGE_W / items.length));
  return new Table({
    width: { size: PAGE_W, type: WidthType.DXA }, columnWidths: cols,
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: C.rule },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: C.rule },
      left: { style: BorderStyle.SINGLE, size: 4, color: C.rule },
      right: { style: BorderStyle.SINGLE, size: 4, color: C.rule },
      insideVertical: { style: BorderStyle.SINGLE, size: 2, color: C.rule },
      insideHorizontal: { style: BorderStyle.NONE },
    },
    rows: [new TableRow({ children: items.map(([v, k, n], i) => new TableCell({
      width: { size: cols[i], type: WidthType.DXA },
      shading: { type: ShadingType.CLEAR, fill: C.card },
      margins: { top: 140, bottom: 140, left: 140, right: 140 },
      children: [
        new Paragraph({ spacing: { after: 30 }, children: [new TextRun({
          text: k.toUpperCase(), font: "Consolas", size: 12, color: INK3, characterSpacing: 20 })] }),
        new Paragraph({ spacing: { after: 30 }, children: [new TextRun({
          text: v, font: "Calibri", size: 28, bold: true, color: INK })] }),
        new Paragraph({ spacing: { after: 0, line: 220 }, children: [new TextRun({
          text: n, font: "Calibri", size: 15, color: INK3 })] }),
      ],
    })) })],
  });
}

function FIGURE(png, number, title, caption, widthIn = 6.3) {
  const file = path.join(FIGDIR, png);
  const data = fs.readFileSync(file);
  // Intrinsic size comes from the PNG header — the figures are rasterised at 2x,
  // so dividing by two gives the drawing's own points.
  const nw = data.readUInt32BE(16), nh = data.readUInt32BE(20);
  const w = Math.round(widthIn * 96);
  return [
    new Paragraph({
      spacing: { before: 200, after: 80 }, alignment: AlignmentType.CENTER,
      children: [new ImageRun({ type: "png", data,
        transformation: { width: w, height: Math.round((w * nh) / nw) } })],
    }),
    new Paragraph({
      spacing: { after: 240 }, alignment: AlignmentType.CENTER,
      children: [
        new TextRun({ text: `Figure ${number} — ${title}. `, font: "Calibri", size: 17, bold: true, color: INK }),
        new TextRun({ text: caption, font: "Georgia", size: 17, italics: true, color: INK3 }),
      ],
    }),
  ];
}

/* ---- assemble ---- */
const children = [];

// cover
children.push(new Paragraph({ spacing: { after: 400 }, children: [new TextRun({
  text: META.eyebrow, font: "Consolas", size: 16, bold: true,
  color: C.accent, characterSpacing: 60 })] }));
children.push(new Paragraph({ spacing: { after: 220 }, children: [
  new TextRun({ text: META.title + ": ", font: "Calibri", size: 64, bold: true, color: INK }),
  new TextRun({ text: META.title_em, font: "Georgia", size: 60, italics: true, color: C.accent }),
] }));
children.push(P(META.sub, { size: 24, line: 340, after: 320 }));
children.push(TBL(["This document", "The other product"], [[
  `${META.product} — reached at ${META.route}. Complete and standalone: everything this product depends on is described here.`,
  `${META.other} — a separate page, a separate pipeline and a separate report. Nothing here requires reading it.`,
]], [0.5, 0.5]));
children.push(GAP(300));
children.push(TBL(["Author", "Report date", "Product", "Chapters"],
  [[META.author, META.date, META.product, String(D.chapters.length + 2)]],
  [0.25, 0.25, 0.28, 0.22]));

// contents
const ENTRIES = [
  ...D.chapters.map((c) => [c.num, `${c.num}. ${c.title}`]),
  [11, "11. SRS Diagrams"],
  [12, "12. Appendix: Prompts, Environment and Reproduction"],
];
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(new Paragraph({ spacing: { after: 240 }, children: [new TextRun({
  text: "CONTENTS", font: "Calibri", size: 26, bold: true, color: INK })] }));
for (const [num, label] of ENTRIES) {
  children.push(new Paragraph({
    spacing: { after: 100, line: 280 },
    children: [new InternalHyperlink({ anchor: `ch${num}`,
      children: [new TextRun({ text: label, font: "Georgia", size: 21, color: INK2 })] })],
  }));
}

// chapters 1..10
for (const ch of D.chapters) {
  children.push(H1(`${ch.num}. ${ch.title}`, `ch${ch.num}`));
  children.push(CHAPNUM(ch.num));
  if (ch.lede) children.push(LEDE(ch.lede));
  for (const b of ch.blocks) {
    switch (b.k) {
      case "p": children.push(P(b.text)); break;
      case "lede": children.push(LEDE(b.text)); break;
      case "h3": children.push(H2(b.text)); break;
      case "h4": children.push(H3(b.text)); break;
      case "ul": for (const i of b.items) children.push(BULLET(i)); children.push(GAP(80)); break;
      case "code": children.push(CODE(b.text), GAP()); break;
      case "note": children.push(NOTE(b.label, b.text, b.tone), GAP()); break;
      case "stats": children.push(STATS(b.items), GAP()); break;
      case "tbl": children.push(TBL(b.headers, b.rows, b.widths), GAP()); break;
      case "fig": children.push(...FIGURE(b.src, b.id, b.title, b.caption)); break;
      default: throw new Error("unknown block " + b.k);
    }
  }
}

// chapter 11 — the SRS diagrams
children.push(H1("11. SRS Diagrams", "ch11"));
children.push(CHAPNUM(11));
children.push(LEDE(D.srsLede));
for (const f of D.srs) {
  children.push(...FIGURE(f.png, f.number, f.title, f.caption));
}

// chapter 12 — appendix
children.push(H1("12. Appendix: Prompts, Environment and Reproduction", "ch12"));
children.push(CHAPNUM(12));
children.push(LEDE(`Every instruction ${META.product} sends to a model, reproduced verbatim from `
  + "source by AST extraction rather than retyped — so this appendix cannot drift from what the "
  + "system actually sends."));
children.push(H2("A. Prompt catalogue"));
children.push(P(`${D.prompts.length} prompts belong to this product. Each entry records the model `
  + "it goes to, the temperature it runs at, where it lives in the source, and why it is worded "
  + "the way it is."));
for (const r of D.prompts) {
  children.push(H3(`P${String(r.n).padStart(2, "0")} · ${r.role}`));
  children.push(P(`${r.model} · temp ${r.temp} · ${r.file} · ${r.name} · ${r.chars} characters`,
    { size: 17, color: INK3, after: 80 }));
  children.push(P(r.note, { size: 19, after: 100 }));
  children.push(CODE(r.text), GAP(200));
}
children.push(H2("B. Environment"));
children.push(TBL(["Component", "Version / detail"], D.env, [0.26, 0.74]));
children.push(GAP());
children.push(H2("C. Reproducing the measurements"));
children.push(TBL(["Command", "What it produces"], D.commands, [0.52, 0.48]));

/* ---- document ---- */
const doc = new Document({
  background: { color: C.paper },
  creator: META.author,
  title: `${META.title} — Product Report`,
  description: `Architecture, requirements and measured results for Cognita's ${META.product}.`,
  numbering: { config: [{ reference: "bullets", levels: [
    { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 360, hanging: 240 } } } },
  ] }] },
  styles: { default: {
    document: { run: { font: "Georgia", size: 21, color: INK2 } },
    heading1: { run: { font: "Calibri", size: 34, bold: true, color: INK } },
    heading2: { run: { font: "Calibri", size: 24, bold: true, color: INK } },
  } },
  sections: [{
    properties: { page: {
      size: { width: 12240, height: 15840 },
      margin: { top: 1440, bottom: 1440, left: 1800, right: 1800 },
    } },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log(`wrote ${path.basename(OUT)} — ${buf.length.toLocaleString()} bytes`);
});
