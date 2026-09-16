"""Assemble the final report: the project report plus a chapter carrying all
nine SRS diagrams, as one self-contained HTML file.

The SRS chapter is spliced in before the appendix, and the diagrams are the
same inline SVG the .docx build rasterises — one source, so the two formats
cannot drift.
"""
import importlib.util
import pathlib
import re

DOCS = pathlib.Path("/Users/princeyadav/Documents/Multi_Agent_AI_Project/"
                    "research-assistant/docs")
SCRATCH = pathlib.Path("/private/tmp/claude-501/"
                       "-Users-princeyadav-Documents-Multi-Agent-AI-Project/"
                       "9b5672a2-05e3-4f1e-9c74-d0adac3299cc/scratchpad")

spec = importlib.util.spec_from_file_location("srs", SCRATCH / "srs-figures.py")
srs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srs)

src = (DOCS / "Cognita-Project-Report.html").read_text()

# ---------------------------------------------------------------- new chapter
legend = """
<figure>
  <figcaption>Figure 11.0 — Notation used throughout this chapter
    <span class="cap">One visual language across all nine diagrams, so it is learned once rather than re-read per figure.</span>
  </figcaption>
  <div class="frame">
    <svg viewBox="0 0 860 92" width="860" height="92" xmlns="http://www.w3.org/2000/svg" role="img">
      <rect width="860" height="92" fill="#ffffff"/>
      <style>
        .k{font-family:'Plus Jakarta Sans',sans-serif;font-size:11px;fill:#16150f;font-weight:600}
        .d{font-family:'JetBrains Mono',monospace;font-size:8.5px;fill:#7c7566}
      </style>
      <rect x="24" y="22" width="96" height="30" rx="8" fill="#fff" stroke="#a06b21" stroke-width="1.6"/>
      <text class="k" x="36" y="41">Process</text>
      <text class="d" x="24" y="70">the system itself</text>

      <path d="M176,29 a48,7 0 0,1 96,0 v16 a48,7 0 0,1 -96,0 z" fill="#f7f4ed" stroke="#1d5f63" stroke-width="1.5"/>
      <path d="M176,29 a48,7 0 0,0 96,0" fill="none" stroke="#1d5f63" stroke-width="1.5"/>
      <text class="k" x="196" y="44">Data store</text>
      <text class="d" x="176" y="70">data at rest</text>

      <path d="M340,22 L424,22 L412,52 L328,52 z" fill="#faf6f8" stroke="#6b3352" stroke-width="1.5"/>
      <text class="k" x="344" y="41">External</text>
      <text class="d" x="328" y="70">outside the boundary</text>

      <rect x="480" y="22" width="96" height="30" rx="8" fill="#eef5f1" stroke="#1f6b4a" stroke-width="1.6"/>
      <text class="k" x="500" y="41">Success</text>
      <text class="d" x="480" y="70">terminal state</text>

      <rect x="632" y="22" width="96" height="30" rx="8" fill="#fbf0ef" stroke="#9c2f26" stroke-width="1.6"/>
      <text class="k" x="656" y="41">Failure</text>
      <text class="d" x="632" y="70">terminal state</text>

      <path d="M776,30 L836,30" stroke="#7c7566" stroke-width="1.4" stroke-dasharray="4 3"/>
      <path d="M776,46 L836,46" stroke="#7c7566" stroke-width="1.4"/>
      <text class="d" x="776" y="70">dashed = conditional</text>
    </svg>
  </div>
</figure>
"""

blocks = [f"""
<section class="chapter" id="ch11">
  <div class="chapter__num">Chapter Eleven</div>
  <h2>SRS Diagrams</h2>
  <p class="lede measure">
    The nine diagrams a complete specification carries, drawn in the same palette as
    the rest of this report rather than a tool's defaults. Colour is not decoration
    here: it separates the system from its data and from everything outside its
    boundary, which is the distinction most of these figures exist to make.
  </p>
  {legend}
"""]

for fid, title, fn, caption in srs.FIGURES:
    number = fid.replace("A.", "11.")
    blocks.append(f"""
  <figure id="fig-{fid.replace('.', '')}">
    <figcaption>Figure {number} — {title}
      <span class="cap">{caption}</span>
    </figcaption>
    <div class="frame">{fn()}</div>
  </figure>
""")

blocks.append("</section>\n")
chapter = "".join(blocks)

# ---------------------------------------------------------------- splice
marker = '<!-- ============================ APPENDIX ============================ -->'
assert marker in src, "appendix marker not found"
src = src.replace(marker, chapter + "\n" + marker)

# Contents entry, inserted before the appendix line.
toc_marker = '<li><a href="#appendix">Appendix: Environment and Reproduction</a></li>'
assert toc_marker in src
src = src.replace(toc_marker,
                  '<li><a href="#ch11">SRS Diagrams</a></li>\n    ' + toc_marker)

# The report's .frame rule forces a 560px minimum on inline SVG, which is right
# for the four charts and wrong for these — they carry their own width now.
src = src.replace(""".frame svg { display: block; width: 100%; height: auto; min-width: 560px; }""",
                  """.frame svg { display: block; width: 100%; height: auto; min-width: 560px; }
/* SRS diagrams declare an intrinsic size so they can be rasterised for Word;
   inside the page they should still scale to the column. */
#ch11 .frame svg { width: 100%; height: auto; }""")

src = src.replace("<title>Cognita — Project Report</title>",
                  "<title>Cognita — Final Project Report</title>")
src = src.replace("<h1>Cognita: research that <em>shows its working</em></h1>",
                  "<h1>Cognita: research that <em>shows its working</em></h1>")

out = DOCS / "Cognita-Final-Report.html"
out.write_text(src)

figs = len(re.findall(r"<figure", src))
print(f"wrote {out.name} — {out.stat().st_size:,} bytes, "
      f"{len(re.findall(r'class=.chapter.', src))} chapters, {figs} figures")
