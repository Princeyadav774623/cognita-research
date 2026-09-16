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
