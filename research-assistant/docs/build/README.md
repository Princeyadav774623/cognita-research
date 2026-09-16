# Rebuilding the documents

The HTML files in `docs/` are the source of truth. The `.docx` files are built
from them and are gitignored — regenerate rather than edit.

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
