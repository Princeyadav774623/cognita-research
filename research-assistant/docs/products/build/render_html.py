"""Render one per-product report to a standalone HTML file, and dump the same
content as JSON so the .docx build reads exactly what the page does.

The two reports are siblings, not twins: they share the type scale, the
structure and the block vocabulary, and each carries its own palette so a reader
can tell at a glance which document is in front of them.
"""
import html
import json
import re
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import figures_research
import figures_files

DOCS = pathlib.Path(__file__).resolve().parents[1]
FIGDIR = pathlib.Path(__file__).parent / "figures"

# --------------------------------------------------------------- palette
# Cognita's own light theme, token for token from frontend/src/index.css, so a
# page in the report and a card in the running application are the same object.
# Both reports share it: the legend, the components and the accent must mean the
# same thing in either document.
COGNITA = dict(
    paper="#f0eee6",          # --bg-app
    paper2="#f5f2ea",
    card="#fbfaf7",           # --bg-card
    rule="#e2ddd2",           # --card-edge, flattened
    rule_soft="#ebe7de",
    ink="#141413",            # --text-primary
    ink2="#4d4c48",           # --text-secondary
    ink3="#6b6965",           # --text-muted
    accent="#a94b2f",         # --accent
    accent_deep="#8f3d25",    # --accent-hover
    accent_soft="rgba(169,75,47,.10)",
    second="#1d5f63",
    second_soft="rgba(29,95,99,.10)",
    good="#2f7d55", warn="#a8690d", bad="#b3402f",
    shadow="0 1px 2px rgba(60,50,38,.04), 0 10px 26px -16px rgba(60,50,38,.22)",
    shadow_sm="0 1px 2px rgba(60,50,38,.05)",
)
PALETTE = {"deep-research": COGNITA, "chat-with-files": COGNITA}

FIGS = {"deep-research": figures_research, "chat-with-files": figures_files}

SRS_LEDE = {
    "deep-research":
        "The nine diagrams a complete specification carries, drawn for this product rather "
        "than for Cognita as a whole. Colour is not decoration here: it separates the pipeline "
        "from its data and from everything outside its boundary, which is the distinction most "
        "of these figures exist to make.",
    "chat-with-files":
        "The nine diagrams a complete specification carries, drawn for this product rather "
        "than for Cognita as a whole. Two paths run through almost all of them and are "
        "deliberately kept apart — ingestion, which happens once per document, and answering, "
        "which happens once per question.",
}


_NS_SEQ = [0]


def namespace_svg(svg_text):
    """Scope one inline SVG's CSS classes and element ids to itself.

    An inline <svg><style> block is a real document stylesheet and its ids share
    the document's id space. Thirteen figures on one page therefore fight over
    `.t`, `.s`, `.ln`, `.band` and `<marker id="a">`, and the last one defined
    wins for all of them — which silently restyles every earlier figure. This
    rewrites each figure into its own namespace at render time, so the figure
    modules can keep using short, readable class names.
    """
    _NS_SEQ[0] += 1
    pre = f"g{_NS_SEQ[0]}"

    def style_block(m):
        body = re.sub(r"\.([A-Za-z][\w-]*)", lambda n: f".{pre}{n.group(1)}", m.group(1))
        return f"<style>{body}</style>"

    out = re.sub(r"<style>(.*?)</style>", style_block, svg_text, flags=re.S)
    out = re.sub(r'class="([^"]*)"',
                 lambda m: 'class="' + " ".join(pre + c for c in m.group(1).split()) + '"',
                 out)
    out = re.sub(r'id="([A-Za-z][\w-]*)"', lambda m: f'id="{pre}{m.group(1)}"', out)
    out = re.sub(r"url\(#([A-Za-z][\w-]*)\)", lambda m: f"url(#{pre}{m.group(1)})", out)
    return out


def esc(t):
    return html.escape(str(t), quote=False)


# --------------------------------------------------------------- blocks
def render_block(b, pal):
    k = b["k"]
    if k == "p":
        return f'<p>{b["text"]}</p>'
    if k == "lede":
        return f'<p class="lede">{b["text"]}</p>'
    if k == "h3":
        return f'<h3>{esc(b["text"])}</h3>'
    if k == "h4":
        return f'<h4>{esc(b["text"])}</h4>'
    if k == "ul":
        items = "".join(f"<li>{i}</li>" for i in b["items"])
        return f"<ul>{items}</ul>"
    if k == "code":
        return f'<pre><code>{esc(b["text"])}</code></pre>'
    if k == "note":
        cls = {"teal": "note", "bronze": "note note--alt", "bad": "note note--caveat"}[b["tone"]]
        return f'<div class="{cls}"><b>{b["label"]}</b> {b["text"]}</div>'
    if k == "stats":
        cells = "".join(
            f'<div class="stat"><div class="stat__k">{esc(k_)}</div>'
            f'<div class="stat__v">{esc(v)}</div>'
            f'<div class="stat__n">{esc(n)}</div></div>'
            for v, k_, n in b["items"])
        return f'<div class="stats">{cells}</div>'
    if k == "tbl":
        head = "".join(f"<th>{esc(h)}</th>" for h in b["headers"])
        body = "".join(
            "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
            for row in b["rows"])
        return (f'<div class="tbl-wrap"><table><thead><tr>{head}</tr></thead>'
                f"<tbody>{body}</tbody></table></div>")
    if k == "fig":
        svg = (FIGDIR / b["src"].replace(".png", ".svg"))
        inner = namespace_svg(svg.read_text()) if svg.exists() else \
            f'<img src="build/figures/{b["src"]}" alt="{esc(b["title"])}">'
        return (f'<figure id="fig-{b["id"].replace(".", "")}">'
                f'<figcaption>Figure {esc(b["id"])} — {esc(b["title"])}'
                f'<span class="cap">{esc(b["caption"])}</span></figcaption>'
                f'<div class="frame">{inner}</div></figure>')
    raise ValueError(k)


def render_chapter(ch, pal, tag=None):
    words = ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
             "Nine", "Ten", "Eleven", "Twelve"]
    out = [f'<section class="chapter" id="ch{ch["num"]}">',
           f'<div class="chapter__num">Chapter {words[ch["num"]-1]}</div>',
           f'<h2>{esc(ch["title"])}</h2>']
    if ch.get("lede"):
        out.append(f'<p class="lede measure">{ch["lede"]}</p>')
    open_measure = False
    for b in ch["blocks"]:
        wide = b["k"] in ("tbl", "fig", "stats")
        if wide and open_measure:
            out.append("</div>")
            open_measure = False
        if not wide and not open_measure:
            out.append('<div class="measure">')
            open_measure = True
        out.append(render_block(b, pal))
    if open_measure:
        out.append("</div>")
    out.append("</section>")
    return "".join(out)


# --------------------------------------------------------------- page
def css(pal):
    return f"""
:root {{
  --paper:{pal['paper']}; --paper-2:{pal['paper2']}; --card:{pal['card']};
  --ink:{pal['ink']}; --ink-2:{pal['ink2']}; --ink-3:{pal['ink3']};
  --rule:{pal['rule']}; --rule-soft:{pal['rule_soft']};
  --accent:{pal['accent']}; --accent-deep:{pal['accent_deep']}; --accent-soft:{pal['accent_soft']};
  --second:{pal['second']}; --second-soft:{pal['second_soft']};
  --good:{pal['good']}; --warn:{pal['warn']}; --bad:{pal['bad']};
  --shadow:{pal['shadow']}; --shadow-sm:{pal['shadow_sm']};
  --serif:"Newsreader",Georgia,"Times New Roman",serif;
  --sans:"Plus Jakarta Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  --mono:"JetBrains Mono",Menlo,Consolas,monospace;
  --r-sm:6px; --r-md:12px; --r-lg:18px; --r-xl:26px; --r-pill:9999px;
  --s1:.25rem; --s2:.5rem; --s3:.75rem; --s4:1rem; --s5:1.5rem; --s6:2rem; --s7:3rem; --s8:4rem;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink); font-family:var(--serif);
       font-size:1rem; line-height:1.68; -webkit-font-smoothing:antialiased;
       /* The prose names real identifiers — test_sources_the_draft_already_used_...
          is a single 60-character token that will otherwise push the page sideways
          at narrow widths. Break only where a word genuinely does not fit. */
       overflow-wrap:break-word; }}
.page {{ max-width:1080px; margin:0 auto; padding:var(--s8) 40px; }}
.measure {{ max-width:68ch; }}

/* ---- the card treatment, shared by every raised block ---- */
.toc, .tbl-wrap, .frame, .stats, .prompt, .pair > div {{
  background:var(--card); border:1px solid var(--rule); border-radius:var(--r-lg);
  box-shadow:var(--shadow);
}}

.cover {{ padding-bottom:var(--s7); margin-bottom:var(--s7);
          border-bottom:1px solid var(--rule); }}
.cover__eyebrow {{ display:inline-block; font-family:var(--mono); font-size:.66rem;
  letter-spacing:.2em; text-transform:uppercase; color:var(--accent);
  background:var(--accent-soft); padding:.4em .9em; border-radius:var(--r-pill);
  margin-bottom:var(--s5); }}
h1 {{ font-family:var(--sans); font-size:clamp(2.4rem,6vw,4rem); font-weight:800;
      letter-spacing:-.042em; line-height:1.02; margin:0 0 var(--s5); text-wrap:balance; }}
h1 em {{ font-family:var(--serif); font-style:italic; font-weight:400; color:var(--accent); }}
.cover__sub {{ font-size:1.2rem; color:var(--ink-2); max-width:58ch; margin:0 0 var(--s6); }}
.cover__meta {{ display:flex; flex-wrap:wrap; gap:var(--s6); padding-top:var(--s5);
                border-top:1px solid var(--rule); }}
.cover__meta div {{ font-family:var(--mono); font-size:.66rem; letter-spacing:.08em;
                    text-transform:uppercase; color:var(--ink-3); }}
.cover__meta b {{ display:block; font-family:var(--sans); font-size:.95rem; color:var(--ink);
                  font-weight:600; letter-spacing:-.01em; text-transform:none; margin-top:4px; }}

.pair {{ display:grid; grid-template-columns:1fr 1fr; gap:var(--s4); margin:var(--s6) 0 0; }}
.pair > div {{ padding:var(--s4) var(--s5); }}
.pair h5 {{ font-family:var(--mono); font-size:.6rem; letter-spacing:.14em;
            text-transform:uppercase; margin:0 0 var(--s2); color:var(--ink-3); }}
.pair p {{ margin:0; font-size:.92rem; color:var(--ink-2); }}
.pair--this {{ border-color:var(--accent); box-shadow:var(--shadow), inset 3px 0 0 var(--accent); }}
.pair--this h5 {{ color:var(--accent); }}

.toc {{ padding:var(--s5) var(--s6); margin-bottom:var(--s8); }}
.toc h2 {{ font-family:var(--mono); font-size:.66rem; letter-spacing:.16em;
           text-transform:uppercase; color:var(--ink-3); margin:0 0 var(--s4);
           border:0; padding:0; font-weight:600; }}
.toc ol {{ margin:0; padding-left:1.5em; columns:2; column-gap:var(--s7); }}
.toc li {{ margin-bottom:var(--s2); break-inside:avoid; }}
.toc a {{ color:var(--ink); text-decoration:none; font-size:.95rem; }}
.toc a:hover {{ color:var(--accent); }}

.chapter {{ margin-bottom:var(--s8); }}
.chapter__num {{ display:inline-block; font-family:var(--mono); font-size:.62rem;
  letter-spacing:.18em; text-transform:uppercase; color:var(--accent);
  background:var(--accent-soft); padding:.35em .8em; border-radius:var(--r-pill);
  margin-bottom:var(--s3); }}
h2 {{ font-family:var(--sans); font-size:1.9rem; font-weight:700; letter-spacing:-.032em;
      margin:0 0 var(--s5); padding-bottom:var(--s3);
      border-bottom:1px solid var(--rule); text-wrap:balance; }}
h3 {{ font-family:var(--sans); font-size:1.1rem; font-weight:700; letter-spacing:-.015em;
      margin:var(--s6) 0 var(--s3); }}
h4 {{ font-family:var(--mono); font-size:.68rem; letter-spacing:.14em; text-transform:uppercase;
      color:var(--ink-3); margin:var(--s5) 0 var(--s2); font-weight:600; }}
p {{ margin:0 0 var(--s4); }}
.lede {{ font-size:1.1rem; color:var(--ink-2); border-left:2px solid var(--accent);
         padding-left:var(--s4); margin-bottom:var(--s5); }}
ul {{ margin:0 0 var(--s5); padding-left:1.2em; }}
li {{ margin-bottom:var(--s2); }}
li::marker {{ color:var(--accent); }}
code {{ font-family:var(--mono); font-size:.84em; background:var(--paper-2);
        border:1px solid var(--rule-soft); border-radius:var(--r-sm); padding:.1em .38em; }}
pre {{ background:var(--paper-2); border:1px solid var(--rule); border-radius:var(--r-md);
       padding:var(--s4); overflow-x:auto; }}
pre code {{ border:0; background:none; padding:0; font-size:.8rem; }}

/* The scroll lives on the wrapper, not the table: making the table itself a
   block with its own overflow inflates the root scrollWidth even though nothing
   is visibly outside the viewport. */
.tbl-wrap {{ overflow-x:auto; margin:var(--s5) 0; }}
table {{ border-collapse:collapse; width:100%; font-family:var(--sans); font-size:.88rem; }}
th {{ text-align:left; font-family:var(--mono); font-size:.62rem; letter-spacing:.12em;
      text-transform:uppercase; color:var(--ink-3); font-weight:600;
      padding:var(--s3) var(--s4); background:var(--paper-2);
      border-bottom:1px solid var(--rule); white-space:nowrap; }}
td {{ padding:var(--s3) var(--s4); border-bottom:1px solid var(--rule-soft);
      color:var(--ink-2); vertical-align:top; }}
tr:last-child td {{ border-bottom:0; }}
td:first-child {{ font-family:var(--mono); font-size:.76rem; color:var(--ink);
                  white-space:nowrap; }}

figure {{ margin:var(--s6) 0; }}
figcaption {{ font-family:var(--mono); font-size:.64rem; letter-spacing:.12em;
              text-transform:uppercase; color:var(--accent); font-weight:600;
              margin-bottom:var(--s3); }}
figcaption .cap {{ display:block; font-family:var(--serif); font-size:.92rem; letter-spacing:0;
                   text-transform:none; color:var(--ink-2); font-weight:400; margin-top:var(--s2); }}
.frame {{ padding:var(--s5); overflow-x:auto; }}
.frame svg {{ display:block; width:100%; height:auto; border-radius:var(--r-md); }}
.frame img {{ display:block; width:100%; height:auto; border-radius:var(--r-md); }}

.note {{ border:1px solid var(--rule); border-left:3px solid var(--second);
         background:var(--second-soft); padding:var(--s4) var(--s5);
         border-radius:var(--r-md); margin:var(--s5) 0; font-size:.95rem; }}
.note--alt {{ border-left-color:var(--accent); background:var(--accent-soft); }}
.note--caveat {{ border-left-color:var(--bad); background:rgba(179,64,47,.07); }}
.note b {{ font-family:var(--sans); color:var(--ink); }}

.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
          overflow:hidden; margin:var(--s5) 0; }}
.stat {{ padding:var(--s4) var(--s5); border-right:1px solid var(--rule-soft); }}
.stat:last-child {{ border-right:0; }}
.stat__k {{ font-family:var(--mono); font-size:.58rem; letter-spacing:.14em;
            text-transform:uppercase; color:var(--ink-3); font-weight:600; }}
.stat__v {{ font-family:var(--sans); font-size:1.6rem; font-weight:700; letter-spacing:-.03em;
            margin-top:4px; font-variant-numeric:tabular-nums; color:var(--ink); }}
.stat__n {{ font-family:var(--sans); font-size:.74rem; color:var(--ink-3); line-height:1.45;
            margin-top:4px; }}

.prompt {{ margin:var(--s4) 0; overflow:hidden; }}
.prompt__head {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:var(--s3);
                 padding:var(--s3) var(--s5); background:var(--paper-2);
                 border-bottom:1px solid var(--rule); }}
.prompt__n {{ font-family:var(--mono); font-size:.7rem; color:var(--accent); font-weight:600; }}
.prompt__role {{ font-family:var(--sans); font-weight:700; font-size:1rem;
                 letter-spacing:-.015em; }}
.prompt__meta {{ margin-left:auto; display:flex; gap:var(--s2); flex-wrap:wrap; }}
.chip {{ font-family:var(--mono); font-size:.6rem; padding:3px 9px; border-radius:var(--r-pill);
         background:var(--accent-soft); color:var(--accent-deep); white-space:nowrap; }}
.prompt__why {{ padding:var(--s3) var(--s5); font-size:.92rem; color:var(--ink-2);
                border-bottom:1px solid var(--rule-soft); }}
.prompt pre {{ margin:0; border:0; border-radius:0; background:var(--card); }}

@media print {{
  body {{ background:#fff; font-size:10.5pt; }}
  .page {{ max-width:none; padding:0; }}
  .chapter {{ break-before:page; }}
  .cover {{ break-after:page; }}
  figure, .tbl-wrap, .note, .stats, .prompt {{ break-inside:avoid; box-shadow:none; }}
  a {{ color:var(--ink); text-decoration:none; }}
}}
@media (max-width:760px) {{
  .page {{ padding:var(--s6) 18px; }}
  .toc ol {{ columns:1; }}
  .pair {{ grid-template-columns:1fr; }}
  .stat {{ border-right:0; border-bottom:1px solid var(--rule-soft); }}
}}
"""


def build(meta, chapters):
    key = meta["key"]
    pal = PALETTE[key]
    figmod = FIGS[key]
    words = ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
             "Nine", "Ten", "Eleven", "Twelve"]

    parts = [
        f'<!-- {meta["title"]} — generated by build/render_html.py; edit the content module -->',
        f"<title>{esc(meta['title'])} — Product Report</title>",
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&'
        'family=Plus+Jakarta+Sans:wght@500;600;700;800&'
        'family=JetBrains+Mono:wght@400;600&display=swap">',
        f"<style>{css(pal)}</style>",
        '<div class="page">',
        # ---- cover
        '<header class="cover">',
        f'<div class="cover__eyebrow">{esc(meta["eyebrow"])}</div>',
        f'<h1>{esc(meta["title"])}: <em>{esc(meta["title_em"])}</em></h1>',
        f'<p class="cover__sub">{esc(meta["sub"])}</p>',
        '<div class="pair">',
        f'<div class="pair--this"><h5>This document</h5>'
        f'<p><b>{esc(meta["product"])}</b> — reached at <code>{esc(meta["route"])}</code>. '
        f'Complete and standalone: everything this product depends on is described here.</p></div>',
        f'<div class="pair--that"><h5>The other product</h5>'
        f'<p><b>{esc(meta["other"])}</b> — a separate page, a separate pipeline and a separate '
        f'report. Nothing here requires reading it.</p></div>',
        "</div>",
        '<div class="cover__meta">',
        f"<div>Author<b>{esc(meta['author'])}</b></div>",
        f"<div>Report date<b>{esc(meta['date'])}</b></div>",
        f"<div>Product<b>{esc(meta['product'])}</b></div>",
        f"<div>Chapters<b>{len(chapters) + 2}</b></div>",
        "</div></header>",
    ]

    # ---- contents
    entries = [(c["num"], c["title"]) for c in chapters]
    entries.append((11, "SRS Diagrams"))
    entries.append((12, "Appendix: Prompts, Environment and Reproduction"))
    parts.append('<nav class="toc"><h2>Contents</h2><ol>')
    for num, title in entries:
        parts.append(f'<li><a href="#ch{num}">{esc(title)}</a></li>')
    parts.append("</ol></nav>")

    # ---- chapters 1..10
    for ch in chapters:
        parts.append(render_chapter(ch, pal))

    # ---- chapter 11: the SRS diagrams
    parts.append('<section class="chapter" id="ch11">'
                 '<div class="chapter__num">Chapter Eleven</div>'
                 "<h2>SRS Diagrams</h2>"
                 f'<p class="lede measure">{SRS_LEDE[key]}</p>')
    parts.append(legend_figure(pal))
    for fid, title, fn, caption in figmod.FIGURES:
        number = fid.split(".")[1]
        parts.append(
            f'<figure id="fig-{fid.replace(".", "")}">'
            f'<figcaption>Figure 11.{number} — {esc(title)}'
            f'<span class="cap">{esc(caption)}</span></figcaption>'
            f'<div class="frame">{namespace_svg(fn())}</div></figure>')
    parts.append("</section>")

    # ---- chapter 12: appendix
    parts.append(appendix(meta, pal))

    parts.append("</div>")
    return "\n".join(parts)


def legend_figure(pal):
    return (f"""<figure>
<figcaption>Figure 11.0 — Notation used throughout this chapter
<span class="cap">One visual language across all nine diagrams, so it is learned once rather than re-read per figure.</span>
</figcaption>
<div class="frame">{namespace_svg(_LEGEND_SVG)}</div></figure>""")


def _legend_svg():
    """The notation key, drawn with the same primitives as the diagrams so it
    cannot describe a visual language the figures no longer use."""
    import draw
    b = draw.box(30, 28, 122, 46, "Process", "the system")
    b += draw.cyl(186, 28, 122, 46, "Data store", "at rest")
    b += draw.para(342, 28, 122, 46, "External", "outside")
    b += draw.box(498, 28, 122, 46, "Success", "terminal", cls="ok")
    b += draw.box(654, 28, 122, 46, "Failure", "terminal", cls="bad")

    b += '<path class="ln" d="M30,104 L86,104"/>'
    b += draw.note(96, 108, ["a step in the flow"])
    b += '<path class="ln dash" d="M232,104 L288,104"/>'
    b += draw.note(298, 108, ["a conditional or optional path"])

    b += draw.note(30, 138, [
        "Shape carries meaning as well as colour: a rounded rectangle is a process, a cylinder is a store,",
        "a slanted parallelogram is something outside the boundary, and a diamond is a decision."])
    return draw.svg(880, 166, b)


_LEGEND_SVG = _legend_svg()


def appendix(meta, pal):
    rows = json.loads((pathlib.Path(__file__).parents[2] / "build" / "prompt-rows.json").read_text())
    mine = [r for r in rows
            if (r["file"].startswith("rag/")) == (meta["key"] == "chat-with-files")]
    out = ['<section class="chapter" id="ch12">'
           '<div class="chapter__num">Chapter Twelve</div>'
           "<h2>Appendix: Prompts, Environment and Reproduction</h2>"
           f'<p class="lede measure">Every instruction {esc(meta["product"])} sends to a model, '
           "reproduced verbatim from source by AST extraction rather than retyped — so this "
           "appendix cannot drift from what the system actually sends.</p>"]
    out.append('<div class="measure"><h3>A. Prompt catalogue</h3>'
               f"<p>{len(mine)} prompts belong to this product. Each entry records the model it "
               "goes to, the temperature it runs at, where it lives in the source, and why it is "
               "worded the way it is.</p></div>")
    for i, r in enumerate(mine, 1):
        out.append(
            f'<article class="prompt"><div class="prompt__head">'
            f'<span class="prompt__n">P{i:02d}</span>'
            f'<span class="prompt__role">{esc(r["role"])}</span>'
            f'<span class="prompt__meta">'
            f'<span class="chip">{esc(r["model"])}</span>'
            f'<span class="chip">temp {esc(r["temp"])}</span>'
            f'<span class="chip">{esc(r["file"])} · {esc(r["name"])}</span>'
            f"</span></div>"
            f'<div class="prompt__why">{esc(r["note"])}</div>'
            f"<pre><code>{esc(r['text'])}</code></pre></article>")

    out.append('<div class="measure"><h3>B. Environment</h3></div>')
    out.append(render_block({"k": "tbl", "headers": ["Component", "Version / detail"], "rows": [
        ["Backend", "Python 3.12, FastAPI 0.121, LangGraph 0.2.76, SQLAlchemy 2.0"],
        ["Frontend", "React 19, Vite 8, TypeScript, Vitest"],
        ["Database", "PostgreSQL 16, pgvector 0.4.1, HNSW + GIN indexes"],
        ["Embeddings", "BAAI/bge-small-en-v1.5, 384 dimensions, local"],
        ["Inference", "openai/gpt-oss-120b (synthesis), openai/gpt-oss-20b (structural, judge)"],
        ["Codebase", "8,807 lines backend · 8,516 lines frontend"],
        ["Tests", "165 backend · 31 frontend"],
    ], "widths": None}, pal))

    cmds = {
        "deep-research": [
            ("pytest -q", "full backend suite"),
            ("python scripts/verify_rls.py", "tenant isolation checks"),
            ("python -m evals.run --answers", "internal golden set"),
            ("python -m evals.factcheck_accuracy --export claims.jsonl", "export claims for labelling"),
            ("python -m evals.factcheck_accuracy --score claims.jsonl", "score the labelled claims"),
        ],
        "chat-with-files": [
            ("pytest -q", "full backend suite"),
            ("npm run test", "frontend suite"),
            ("python scripts/verify_rls.py", "tenant isolation checks"),
            ("python -m evals.squad --retrieval --questions 200", "public benchmark, no API cost"),
            ("python -m evals.squad --answers --questions 25", "answer pass, uses the token budget"),
        ],
    }[meta["key"]]
    out.append('<div class="measure"><h3>C. Reproducing the measurements</h3></div>')
    out.append(render_block({"k": "tbl", "headers": ["Command", "What it produces"],
                             "rows": [[f"<code>{esc(c)}</code>", esc(d)] for c, d in cmds],
                             "widths": None}, pal))
    out.append("</section>")
    return "".join(out)


def plain(t):
    """Strip the light inline markup the HTML blocks carry, for the .docx build.

    Word gets the same words; it does not get <b> and <code>, which would
    otherwise arrive as literal angle brackets in the document.
    """
    t = re.sub(r"<[^>]+>", "", str(t))
    return html.unescape(t)


def docx_payload(meta, chapters):
    """Everything the Node build needs, so the two formats read one source."""
    figmod = FIGS[meta["key"]]

    def block(b):
        b = dict(b)
        if b["k"] in ("p", "lede", "h3", "h4", "note"):
            b["text"] = plain(b["text"])
        if b["k"] == "note":
            b["label"] = plain(b["label"])
        if b["k"] == "ul":
            b["items"] = [plain(i) for i in b["items"]]
        if b["k"] == "tbl":
            b["headers"] = [plain(h) for h in b["headers"]]
            b["rows"] = [[plain(c) for c in row] for row in b["rows"]]
        return b

    rows = json.loads((pathlib.Path(__file__).parents[2] / "build" / "prompt-rows.json").read_text())
    mine = [r for r in rows
            if (r["file"].startswith("rag/")) == (meta["key"] == "chat-with-files")]

    return {
        "meta": meta,
        "chapters": [{"num": c["num"], "title": c["title"], "lede": plain(c["lede"]),
                      "blocks": [block(b) for b in c["blocks"]]} for c in chapters],
        "srsLede": SRS_LEDE[meta["key"]],
        "srs": [{"id": "11.0", "number": "11.0", "title": "Notation used throughout this chapter",
                 "caption": "One visual language across all nine diagrams, so it is learned "
                            "once rather than re-read per figure.",
                 "png": "fig-legend.png"}]
               + [{"id": fid, "number": "11." + fid.split(".")[1], "title": t,
                 "caption": cap, "png": "fig-" + fid.replace(".", "").lower() + ".png"}
                for fid, t, fn, cap in figmod.FIGURES],
        "prompts": [{"n": i, **r} for i, r in enumerate(mine, 1)],
        "env": ENV,
        "commands": COMMANDS[meta["key"]],
    }


ENV = [
    ["Backend", "Python 3.12, FastAPI 0.121, LangGraph 0.2.76, SQLAlchemy 2.0"],
    ["Frontend", "React 19, Vite 8, TypeScript, Vitest"],
    ["Database", "PostgreSQL 16, pgvector 0.4.1, HNSW + GIN indexes"],
    ["Embeddings", "BAAI/bge-small-en-v1.5, 384 dimensions, local"],
    ["Inference", "openai/gpt-oss-120b (synthesis), openai/gpt-oss-20b (structural, judge)"],
    ["Codebase", "8,807 lines backend · 8,516 lines frontend"],
    ["Tests", "165 backend · 31 frontend"],
]

COMMANDS = {
    "deep-research": [
        ["pytest -q", "full backend suite"],
        ["python scripts/verify_rls.py", "tenant isolation checks"],
        ["python -m evals.run --answers", "internal golden set"],
        ["python -m evals.factcheck_accuracy --export claims.jsonl", "export claims for labelling"],
        ["python -m evals.factcheck_accuracy --score claims.jsonl", "score the labelled claims"],
    ],
    "chat-with-files": [
        ["pytest -q", "full backend suite"],
        ["npm run test", "frontend suite"],
        ["python scripts/verify_rls.py", "tenant isolation checks"],
        ["python -m evals.squad --retrieval --questions 200", "public benchmark, no API cost"],
        ["python -m evals.squad --answers --questions 25", "answer pass, uses the token budget"],
    ],
}


def main():
    import content_research
    import content_files
    for mod in (content_research, content_files):
        meta, chapters = mod.META, mod.CHAPTERS
        html_out = build(meta, chapters)
        name = {"deep-research": "Cognita-Deep-Research-Report.html",
                "chat-with-files": "Cognita-Chat-with-Files-Report.html"}[meta["key"]]
        (DOCS / name).write_text(html_out)
        # the same content, for the .docx build
        (pathlib.Path(__file__).parent / f"{meta['key']}.json").write_text(
            json.dumps(docx_payload(meta, chapters), indent=1))
        print(f"{name} — {len(html_out):,} bytes, "
              f"{len(chapters) + 2} chapters, "
              f"{html_out.count('<figure')} figures, "
              f"{html_out.count('<table')} tables")


if __name__ == "__main__":
    main()
