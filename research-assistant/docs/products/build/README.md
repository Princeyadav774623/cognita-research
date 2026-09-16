# The two per-product reports

Cognita is two products over one shared platform. `docs/` holds the combined
report that covers both; this folder holds one complete, standalone report for
each, so a reader interested in only one never has to read around the other.

| | Deep Research | Chat with Files |
|---|---|---|
| Report | `Cognita-Deep-Research-Report.{html,docx}` | `Cognita-Chat-with-Files-Report.{html,docx}` |
| Content | `build/content_research.py` | `build/content_files.py` |
| Diagrams | `build/figures_research.py` (R.1–R.9) | `build/figures_files.py` (F.1–F.9) |
| Palette | Cognita's own light theme — shared | Cognita's own light theme — shared |

## Rebuild both

```bash
docs/products/build/build.sh
```

That runs `render_html.py` (which writes both HTML files *and* a JSON payload
per product) and then `render-docx.js` twice against those payloads, and
renumbers bookmarks. Nothing else needs running.

## One theme, from the application's own tokens

`draw.py` and the stylesheet in `render_html.py` both take their palette from
`frontend/src/index.css` rather than inventing one: ground `#f0eee6`, card
`#fbfaf7`, accent `#a94b2f`, the card shadow, the radius scale, and the three
faces. A figure in the report and a card in the running product are the same
object.

Both reports share it. An earlier pass gave each document its own accent; that
was wrong — the legend says "process", "data store", "external", and those
meanings must not change colour depending on which document you opened. The two
are told apart by their titles and by the "one of two" / "two of two" eyebrow,
not by their palette.

`figures_research.py` and `figures_files.py` still import `BRONZE`; it is an
alias for the accent, kept rather than renamed through eighteen figures.

## Deliberate duplication

Chapters on the database, the security model and CI appear in **both** reports,
written out in full rather than cross-referenced. That is the point: each
document is complete on its own. If you change one of those chapters, change it
in both content modules — there is no shared include, because a shared include
would make the two documents' prose drift toward the generic.

What must stay *different* is anything a reader could act on: the requirement
IDs (`DR-*` vs `CF-*`), the measurements, the limitations and the diagrams.

## One source, two formats

`render_html.py` is the only place content is read. It emits the HTML directly
and dumps `deep-research.json` / `chat-with-files.json` for the Node build, so
the `.docx` cannot say something the page does not. Inline markup (`<b>`,
`<code>`) is stripped for Word by `plain()`.

## Two things that will bite

**Namespace every inline SVG.** An inline `<svg><style>` block is a real
document stylesheet and its `id`s share the document's id space. Thirteen
figures on one page otherwise fight over `.t`, `.s`, `.ln`, `.band` and
`<marker id="a">`, and the last definition wins for all of them — silently
restyling every earlier figure. `namespace_svg()` rewrites each figure into its
own prefix at render time. Pass it **only** an `<svg>` element: given
surrounding HTML it will happily rewrite `class="frame"` too and break the page.

**Re-rasterise after any change to `draw.py`.** The `.docx` figures are PNGs
baked from the SVGs; changing a primitive updates the HTML immediately and
leaves Word showing the old drawing until the PNGs are regenerated.

**Keep the explicit `width`/`height` on every SVG.** Without an intrinsic size a
browser rasterising the SVG to a canvas falls back to its own default and
produces an image far smaller than the drawing.

## Regenerating the figure PNGs

Word needs raster images. There is no SVG rasteriser on this machine —
`rsvg-convert`, ImageMagick and `cairosvg` are all absent and `soffice` is a
broken symlink — and macOS `qlmanage` pads the output to a square and crops
wrong. The PNGs in `figures/` were produced by rendering each SVG to a canvas in
a browser at 2× and posting the bytes to a local receiver.

If you have a real rasteriser this is one line:

```bash
rsvg-convert -z 2 build/figures/fig-r3.svg -o build/figures/fig-r3.png
```

Keep the 2× scale — at 1× the line work is visibly soft in print. The `.docx`
build reads each PNG's intrinsic size from its header and halves it, so a figure
rasterised at 1× would come out twice its intended size on the page.

## No TOC field, and a page background

Both documents carry a plain hyperlinked chapter list rather than a Word TOC
field, so Word opens them without the *"contains fields that may refer to other
files"* dialog. Both also set a page background matching their HTML palette —
Word shows it on screen but will not print it unless the reader enables
*Options → Display → Print background colors and images*.
