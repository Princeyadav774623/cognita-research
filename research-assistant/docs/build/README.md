# Rebuilding the documents

`Cognita-Final-Report.html` is the deliverable: the full project report plus
Chapter 11 carrying all nine SRS diagrams. The HTML files are the source of
truth; the `.docx` files are built from them and are gitignored — regenerate
rather than edit.

## Rebuild the final report (the one to hand in)

```bash
cd research-assistant/docs
python3 build/final-html.py                  # report + chapter 11, one file
cp build/report-docx.js ./_b.js
node ./_b.js build/figures Cognita-Final-Report.docx
rm ./_b.js
python3 build/fix-bookmarks.py Cognita-Final-Report.docx
```

`final-html.py` splices Chapter 11 into `Cognita-Project-Report.html`, so edit
the base report for chapters 1–10 and `build/srs-figures.py` for the diagrams —
never the combined file, which is regenerated each time.

## The SRS diagrams

`build/srs-figures.py` draws all nine as SVG in the report's palette. One
visual language throughout: bronze is a process, teal is data at rest, plum is
an external service, green and red are terminal states, dashed is conditional.
Shape carries meaning too — cylinder for a store, slanted parallelogram for
something outside the boundary.

Two things that will bite if you edit it:

- **Escape label text.** A label containing `<document>` — and one does, because
  the RAG prompt wraps excerpts in those tags — produces an SVG that silently
  fails to parse. Everything goes through `esc()`.
- **Keep the explicit `width`/`height`.** Without an intrinsic size, a browser
  rasterising the SVG falls back to its own default and produces an image far
  smaller than the drawing — the first attempt came out 600px wide instead of
  1760.

## The two products must stay visible

Cognita is two products — Deep Research and Chat with Files — over one shared
platform. That is obvious in the code (`agents/` and `graph/` versus `rag/`)
and in the app (two routes, two query boxes), and it was almost invisible in
this report: both product names appeared three times in 7,200 words, and never
in the eight chapters that describe them.

Four things carry the distinction now, and they need to stay in step:

- **§1.2 "Two products, one platform"** — the comparison table, Figure 1.1, and
  the statement of the one crossing point (the corpus node, FR-6). Without that
  last paragraph a reader finishing Chapter 4 concludes that Chapter 5's RAG is
  a *stage of the research pipeline*, which is wrong.
- **A badge on every chapter opener and every contents entry**, from
  `CONTENTS_TAGS` in `report-docx.js` and `.tag--research/files/shared` in the
  HTML. Add a chapter, add its badge in both.
- **A Product column on the functional requirements table.** FR-1…FR-12 and
  FR-15 are Deep Research, FR-13/FR-14 are Chat with Files, FR-16/FR-17 are
  shared, and FR-6 is the crossing point and carries both.
- **A product label on every appendix prompt**, derived from the source path —
  `rag/` is Chat with Files, everything else is Deep Research. Derived, not
  hand-listed, so it cannot go stale.

Figure 1.1 lives in `Cognita-Project-Report.html` as inline SVG and is extracted
to `build/figures/fig1-boundary.svg` / `.png`. Its CSS classes are prefixed
`bd` on purpose: inline SVG `<style>` is a real document stylesheet, so the
single-letter class names the other figures use collide across figures.

## Prerequisites

`node` with the `docx` package resolvable from `docs/`, and `python3`. No
LibreOffice or SVG renderer is needed; the figures are already rasterised in
`figures/`.

## Rebuild the project report

```bash
cd research-assistant/docs
cp build/report-docx.js ./_b.js
node ./_b.js build/figures Cognita-Project-Report.docx
rm ./_b.js
python3 build/fix-bookmarks.py Cognita-Project-Report.docx
```

The copy step exists because `require("docx")` resolves relative to the script,
and the package is reachable from `docs/` but not from `docs/build/`.

## Rebuild the technical appendix

```bash
cd research-assistant/docs
python3 build/appendix-html.py                      # regenerates the HTML
cp build/appendix-docx.js ./_a.js
node ./_a.js build/prompt-rows.json build/figs-spec.json Cognita-Technical-Appendix.docx
rm ./_a.js
python3 build/fix-bookmarks.py Cognita-Technical-Appendix.docx
```

## No TOC field, on purpose

An earlier build used a Word TOC field with `updateFields`, which makes Word
open the document with *"This document contains fields that may refer to other
files. Do you want to update the fields?"* — wording that reads as a security
warning to anyone you send it to, for what is only a table of contents.

Both documents now carry a plain hyperlinked chapter list instead. It renders
in Word, Google Docs, Preview and anything else, needs no refresh, and opens
without a dialog. The cost is page numbers in the contents, which is a fair
trade for a document that is mostly read on screen.

Do not reintroduce `features: { updateFields: true }`.

## Page background

Both documents set `background: { color: "F4F1EA" }` — the HTML report's
`--paper` — so the two formats read the same. `docx-js` writes the matching
`<w:displayBackgroundShape/>` into `settings.xml` for you.

Anything that is a card in the HTML stays white on top of it: table cells take
an explicit `FFFFFF` fill (previously they had none and would otherwise inherit
the cream), and the rasterised figures already carry a white plate.

Word shows the background on screen but does **not** print it unless the reader
turns on *Options → Display → Print background colors and images*. That is
Word's default, not a defect in the file — printed copies come out on white.

## Always run fix-bookmarks.py

`docx-js` writes `w:id="1"` on every bookmark it emits. The bookmark *names*
are unique, so Word navigates correctly and the problem is invisible in normal
use — but duplicate numeric ids violate the OOXML schema, and a stricter
consumer will reject the file. The script renumbers them in document order.

Verify afterwards:

```bash
python3 <skills>/docx/scripts/office/validate.py Cognita-Project-Report.docx
```

## Refreshing the prompt catalogue

`prompt-rows.json` holds the prompts extracted from the backend source by AST,
plus the commentary on each. When a prompt changes in the code, re-extract it
rather than editing the JSON by hand — the point of extracting is that this
document cannot drift from what the system actually sends.

## Regenerating the figures

The four report figures are inline SVG inside `Cognita-Project-Report.html`.
`figures/` holds both the extracted `.svg` and a 2× `.png` of each.

There was no SVG rasteriser on the build machine — no `rsvg-convert`, no
ImageMagick, no `cairosvg`, and `soffice` was a broken symlink — so the PNGs
were produced by rendering each SVG to a canvas in a browser and posting the
bytes to a local receiver. If you have a rasteriser, this is simpler:

```bash
rsvg-convert -z 2 figures/fig3-architecture.svg -o figures/fig3-architecture.png
```

Keep the 2× scale. At 1× the line work is visibly soft in print.

The nine appendix figures are Mermaid sources inside the appendix, not images.
Render them with `mmdc` if you need image files — see Part C of the appendix.
