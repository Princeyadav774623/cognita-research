"""Diagram primitives in Cognita's own design language.

The tokens here are lifted from frontend/src/index.css rather than invented, so
a diagram in the report and a card in the running application are recognisably
the same product: the same ground, the same card white, the same soft shadow,
the same radius scale, the same three type faces.

What each figure module gets from this:

    set_accent(...)   the report's accent — terracotta for Deep Research, teal
                      for Chat with Files. Everything else is shared.
    box / cyl / para  a process, a store, something outside the boundary
    arrow / elbow     connectors with rounded corners and knockout labels
    chip / index      small pills, for step numbers and legends

The visual language itself is unchanged from the earlier figures, so a reader
who learned it once does not have to relearn it:

    accent   the system under discussion      green   terminal success
    teal     data at rest                     red     terminal failure
    plum     an external service              dashed  conditional
"""
import math
from xml.sax.saxutils import escape as _esc


def esc(text):
    """Escape label text. Labels legitimately contain angle brackets — the RAG
    prompt wraps excerpts in <document> tags — and pasting those raw produces an
    SVG that silently fails to parse."""
    return _esc(str(text))


# ---- Cognita tokens (frontend/src/index.css, light theme) ----
BG_APP = "#f0eee6"
BG_CARD = "#fbfaf7"
CARD_EDGE = "#e2ddd2"
INK = "#141413"
INK2 = "#4d4c48"
INK3 = "#6b6965"
RULE = "#ddd8cc"

TERRACOTTA = "#a94b2f"
TEAL = "#1d5f63"
PLUM = "#6b3352"
GREEN = "#2f7d55"
RED = "#b3402f"
AMBER = "#a8690d"

SERIF = "'Newsreader',Georgia,serif"
SANS = "'Plus Jakarta Sans',-apple-system,BlinkMacSystemFont,sans-serif"
MONO = "'JetBrains Mono',Menlo,Consolas,monospace"

R_SM, R_MD, R_LG = 6, 12, 18

# The accent the current report leads with. Figure modules set this once.
ACCENT = TERRACOTTA
ACCENT_TINT = "#fdf6f3"


def set_accent(hex_colour, tint):
    global ACCENT, ACCENT_TINT
    ACCENT, ACCENT_TINT = hex_colour, tint


def _defs():
    """Markers, the card shadow, and the type scale — emitted per figure."""
    marks = "".join(
        f'<marker id="ar-{k}" viewBox="0 0 10 10" refX="8.5" refY="5" '
        f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M0,1 L9,5 L0,9 z" fill="{v}"/></marker>'
        for k, v in (("n", INK3), ("a", ACCENT), ("t", TEAL), ("p", PLUM),
                     ("g", GREEN), ("r", RED)))
    return f"""<defs>{marks}
<filter id="card" x="-25%" y="-25%" width="150%" height="170%">
  <feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#3c3226" flood-opacity="0.13"/>
</filter>
<filter id="lift" x="-25%" y="-25%" width="150%" height="170%">
  <feDropShadow dx="0" dy="1" stdDeviation="1.6" flood-color="#3c3226" flood-opacity="0.10"/>
</filter>
</defs>
<style>
 .ttl {{ font-family:{SANS}; font-size:12px; font-weight:700; fill:{INK};
        letter-spacing:-.01em; text-anchor:middle }}
 .sub {{ font-family:{MONO}; font-size:8.2px; fill:{INK3}; text-anchor:middle }}
 .lbl {{ font-family:{MONO}; font-size:8.4px; fill:{INK2} }}
 .lblc{{ font-family:{MONO}; font-size:8.4px; fill:{INK2}; text-anchor:middle }}
 .eyb {{ font-family:{MONO}; font-size:8.6px; font-weight:600; letter-spacing:.14em }}
 .idx {{ font-family:{MONO}; font-size:8px; font-weight:600; text-anchor:middle }}
 .note{{ font-family:{SANS}; font-size:9.4px; fill:{INK3} }}
 .ln  {{ fill:none; stroke:{INK3}; stroke-width:1.25; stroke-linecap:round;
        marker-end:url(#ar-n) }}
 .lna {{ fill:none; stroke:{ACCENT}; stroke-width:1.5; stroke-linecap:round;
        marker-end:url(#ar-a) }}
 .lnt {{ fill:none; stroke:{TEAL}; stroke-width:1.4; stroke-linecap:round;
        marker-end:url(#ar-t) }}
 .lnp {{ fill:none; stroke:{PLUM}; stroke-width:1.4; stroke-linecap:round;
        marker-end:url(#ar-p) }}
 .dash{{ stroke-dasharray:5 4; stroke-opacity:.85 }}
</style>"""


def svg(vb_w, vb_h, body):
    # Explicit width/height as well as viewBox: without an intrinsic size a
    # browser rasterising this to a canvas falls back to its own default and
    # produces an image far smaller than the drawing.
    return (f'<svg viewBox="0 0 {vb_w} {vb_h}" width="{vb_w}" height="{vb_h}" '
            f'xmlns="http://www.w3.org/2000/svg" role="img">'
            f'<rect width="{vb_w}" height="{vb_h}" fill="{BG_CARD}"/>'
            f"{_defs()}{body}</svg>")


# ------------------------------------------------------------------ shapes
_KIND = {
    # cls name -> (stroke, fill, stroke width)
    "proc": (None, None, 1.5),                  # None = the report's accent
    "store": (TEAL, "#eef4f4", 1.4),
    "ext": (PLUM, "#f9f2f6", 1.4),
    "ok": (GREEN, "#eef5f0", 1.5),
    "bad": (RED, "#fbf0ee", 1.5),
    "band": (RULE, "#f4f1e9", 1.1),
}


def _skin(cls):
    stroke, fill, w = _KIND.get(cls, _KIND["proc"])
    return (stroke or ACCENT, fill or ACCENT_TINT, w)


def box(x, y, w, h, label, sub="", cls="proc", rx=R_MD, index=None):
    """A process. Title in the sans at full weight, sub-label in mono beneath it
    at lower contrast — so the eye reads what a node *is* before what it does."""
    stroke, fill, sw = _skin(cls)
    out = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
           f'stroke="{stroke}" stroke-width="{sw}" filter="url(#card)"/>')
    cx = x + w / 2
    ty = y + h / 2 + (4 if not sub else -2)
    if index is not None:
        out += chip(x + 11, y + 9, str(index), stroke)
    out += f'<text class="ttl" x="{cx}" y="{ty}">{esc(label)}</text>'
    if sub:
        out += f'<text class="sub" x="{cx}" y="{ty + 15}">{esc(sub)}</text>'
    return out


def cyl(x, y, w, h, label, sub=""):
    """Data at rest, drawn as a cylinder."""
    r = 7
    out = (f'<g filter="url(#card)">'
           f'<path d="M{x},{y+r} a{w/2},{r} 0 0,1 {w},0 v{h-2*r} '
           f'a{w/2},{r} 0 0,1 -{w},0 z" fill="#eef4f4" stroke="{TEAL}" stroke-width="1.4"/>'
           f'<path d="M{x},{y+r} a{w/2},{r} 0 0,0 {w},0" fill="none" stroke="{TEAL}" '
           f'stroke-width="1.4"/></g>')
    cx, ty = x + w / 2, y + h / 2 + (4 if not sub else -2)
    out += f'<text class="ttl" x="{cx}" y="{ty}">{esc(label)}</text>'
    if sub:
        out += f'<text class="sub" x="{cx}" y="{ty + 15}">{esc(sub)}</text>'
    return out


def para(x, y, w, h, label, sub=""):
    """Something outside the boundary: a slanted parallelogram."""
    k = 12
    out = (f'<path d="M{x+k},{y} L{x+w},{y} L{x+w-k},{y+h} L{x},{y+h} z" '
           f'fill="#f9f2f6" stroke="{PLUM}" stroke-width="1.4" filter="url(#card)"/>')
    cx, ty = x + w / 2, y + h / 2 + (4 if not sub else -2)
    out += f'<text class="ttl" x="{cx}" y="{ty}">{esc(label)}</text>'
    if sub:
        out += f'<text class="sub" x="{cx}" y="{ty + 15}">{esc(sub)}</text>'
    return out


def diamond(cx, cy, w, h, label):
    out = (f'<path d="M{cx},{cy-h/2} L{cx+w/2},{cy} L{cx},{cy+h/2} L{cx-w/2},{cy} z" '
           f'fill="{ACCENT_TINT}" stroke="{ACCENT}" stroke-width="1.5" filter="url(#card)"/>')
    out += f'<text class="ttl" x="{cx}" y="{cy+4}">{esc(label)}</text>'
    return out


def ellipse(cx, cy, rx, ry, label, sub=""):
    out = (f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{ACCENT_TINT}" '
           f'stroke="{ACCENT}" stroke-width="1.4" filter="url(#lift)"/>')
    out += f'<text class="ttl" x="{cx}" y="{cy+4}">{esc(label)}</text>'
    return out


def actor(x, y, label):
    """Stick figure — the one shape everyone reads as 'a person'."""
    return (f'<g stroke="{ACCENT}" stroke-width="1.7" fill="none" stroke-linecap="round">'
            f'<circle cx="{x}" cy="{y}" r="7.5"/>'
            f'<path d="M{x},{y+8} v15 M{x-10},{y+13} h20 M{x},{y+23} l-8,11 '
            f'M{x},{y+23} l8,11"/></g>'
            f'<text class="ttl" x="{x}" y="{y+49}">{esc(label)}</text>')


def band(x, y, w, h, label, colour=None):
    """A labelled boundary the system under discussion sits inside.

    The caption sits at the top left, not centred. Centred, it lands in the
    middle of the band's top edge — exactly where a connector descending from
    the tier above crosses into it, which struck the caption through in two of
    the layered diagrams.
    """
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{R_LG}" '
            f'fill="#f4f1e9" stroke="{RULE}" stroke-width="1.1"/>'
            f'<text class="eyb" x="{x+16}" y="{y+21}" '
            f'fill="{colour or ACCENT}">{esc(label)}</text>')


def lane(x, y, w, h, title, colour=INK3):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{R_MD}" fill="{BG_CARD}" '
            f'stroke="{RULE}" stroke-width="1"/>'
            f'<text class="eyb" x="{x+w/2}" y="{y+20}" text-anchor="middle" '
            f'fill="{colour}">{esc(title)}</text>')


# ------------------------------------------------------------------ chips
def chip(x, y, text, colour=None, pad=5):
    """A small pill — a step index, or a legend swatch label."""
    colour = colour or ACCENT
    w = max(14, len(str(text)) * 5.2 + pad * 2)
    return (f'<rect x="{x-w/2}" y="{y-7}" width="{w}" height="14" rx="7" '
            f'fill="#fff" stroke="{colour}" stroke-width="1"/>'
            f'<text class="idx" x="{x}" y="{y+3}" fill="{colour}">{esc(text)}</text>')


def _knockout(x, y, text, size=8.4):
    """A label plate, so a connector label never sits on top of its own line."""
    w = len(str(text)) * (size * 0.6) + 10
    return (f'<rect x="{x-w/2}" y="{y-8.5}" width="{w}" height="13" rx="4" '
            f'fill="{BG_CARD}" fill-opacity=".95"/>')


# ------------------------------------------------------------------ lines
def _round_path(pts, r=9):
    """An orthogonal path with rounded corners — the single biggest difference
    between a diagram that looks drawn and one that looks generated."""
    if len(pts) < 3:
        return f"M{pts[0][0]},{pts[0][1]} " + " ".join(f"L{x},{y}" for x, y in pts[1:])
    d = [f"M{pts[0][0]},{pts[0][1]}"]
    for i in range(1, len(pts) - 1):
        p0, p1, p2 = pts[i - 1], pts[i], pts[i + 1]
        v1 = (p1[0] - p0[0], p1[1] - p0[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        l1 = math.hypot(*v1) or 1
        l2 = math.hypot(*v2) or 1
        rr = min(r, l1 / 2, l2 / 2)
        a = (p1[0] - v1[0] / l1 * rr, p1[1] - v1[1] / l1 * rr)
        b = (p1[0] + v2[0] / l2 * rr, p1[1] + v2[1] / l2 * rr)
        d.append(f"L{a[0]:.1f},{a[1]:.1f}")
        d.append(f"Q{p1[0]},{p1[1]} {b[0]:.1f},{b[1]:.1f}")
    d.append(f"L{pts[-1][0]},{pts[-1][1]}")
    return " ".join(d)


_CLS = {"ln": "ln", "lnb": "lna", "lna": "lna", "lnt": "lnt", "lnp": "lnp"}


def arrow(x1, y1, x2, y2, cls="ln", label="", dash=False, lx=None, ly=None):
    c = _CLS.get(cls, "ln") + (" dash" if dash else "")
    out = f'<path class="{c}" d="M{x1},{y1} L{x2},{y2}"/>'
    if label:
        tx = lx if lx is not None else (x1 + x2) / 2
        ty = ly if ly is not None else (y1 + y2) / 2 - 7
        out += _knockout(tx, ty, label) + f'<text class="lblc" x="{tx}" y="{ty}">{esc(label)}</text>'
    return out


def elbow(pts, cls="ln", label="", dash=False, lx=None, ly=None):
    c = _CLS.get(cls, "ln") + (" dash" if dash else "")
    out = f'<path class="{c}" d="{_round_path(pts)}"/>'
    if label and lx is not None:
        out += _knockout(lx, ly, label) + f'<text class="lblc" x="{lx}" y="{ly}">{esc(label)}</text>'
    return out


def note(x, y, text, colour=INK3):
    """A short annotation, on a knockout plate.

    Notes sit next to connectors, and a connector that happens to pass beneath
    one would otherwise strike the words through. The plate is the card colour,
    so over a card it is invisible and over a line it is the point.
    """
    lines = text if isinstance(text, (list, tuple)) else [text]
    out = ""
    for i, ln in enumerate(lines):
        ty = y + i * 13.5
        w = len(str(ln)) * 5.15 + 8
        out += (f'<rect x="{x-4}" y="{ty-8.5}" width="{w:.0f}" height="12.5" rx="3" '
                f'fill="{BG_CARD}" fill-opacity=".88"/>')
        out += f'<text class="note" x="{x}" y="{ty}" fill="{colour}">{esc(ln)}</text>'
    return out


# ------------------------------------------------------------------ sequence
def lifeline(x, top, bottom, label, kind="proc"):
    w, h = 148, 36
    out = box(x - w / 2, top, w, h, label, cls=kind, rx=R_MD)
    out += (f'<path d="M{x},{top+h} L{x},{bottom}" stroke="{RULE}" stroke-width="1.2" '
            f'stroke-dasharray="3 5" fill="none"/>')
    return out


def msg(x1, x2, y, label, cls="ln", dash=False):
    c = _CLS.get(cls, "ln") + (" dash" if dash else "")
    out = f'<path class="{c}" d="M{x1},{y} L{x2},{y}"/>'
    mx = (x1 + x2) / 2
    out += _knockout(mx, y - 7, label) + f'<text class="lblc" x="{mx}" y="{y-7}">{esc(label)}</text>'
    return out


def selfmsg(x, y, label, w=54):
    out = f'<path class="ln" d="{_round_path([(x, y), (x+w, y), (x+w, y+20), (x+4, y+20)], 6)}"/>'
    out += f'<text class="lbl" x="{x+w+9}" y="{y+14}">{esc(label)}</text>'
    return out


def activation(x, y, h, colour=None):
    return (f'<rect x="{x-5}" y="{y}" width="10" height="{h}" fill="#fff" '
            f'stroke="{colour or ACCENT}" stroke-width="1.2"/>')


# ------------------------------------------------------------------ er
def entity(x, y, w, title, fields, pk=None):
    """ER box: a tinted title bar over a list of columns."""
    rows = len(fields)
    h = 30 + rows * 15 + 10
    out = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{R_MD}" fill="{BG_CARD}" '
           f'stroke="{TEAL}" stroke-width="1.4" filter="url(#card)"/>'
           f'<path d="M{x+1},{y+30} h{w-2}" stroke="{TEAL}" stroke-width="1.1" opacity=".45"/>')
    out += f'<text class="ttl" x="{x+w/2}" y="{y+20}">{esc(title)}</text>'
    for i, f in enumerate(fields):
        mark = "PK" if f == pk else ("FK" if f.endswith("_id") and f != pk else "")
        out += f'<text class="lbl" x="{x+12}" y="{y+46+i*15}">{esc(f)}</text>'
        if mark:
            out += (f'<text class="lbl" x="{x+w-12}" y="{y+46+i*15}" text-anchor="end" '
                    f'fill="{ACCENT}" font-weight="600">{mark}</text>')
    return out, h


def legend(x, y, items):
    """Key strip: a swatch and a label per entry, laid out in a row."""
    out, cx = "", x
    for colour, label in items:
        out += (f'<rect x="{cx}" y="{y}" width="12" height="12" rx="4" fill="#fff" '
                f'stroke="{colour}" stroke-width="1.6"/>')
        out += f'<text class="lbl" x="{cx+18}" y="{y+9.5}">{esc(label)}</text>'
        cx += 26 + len(label) * 5.2
    return out
