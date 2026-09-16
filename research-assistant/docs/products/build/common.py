"""Shared drawing primitives for the two per-product reports.

Re-exports the primitives from the combined report's figure module so all three
documents speak one visual language, and adds the few shapes the per-product
diagrams need that the combined report never did.
"""
import importlib.util
import pathlib

_SRS = pathlib.Path(__file__).resolve().parents[2] / "build" / "srs-figures.py"
_spec = importlib.util.spec_from_file_location("srs_figures", _SRS)
srs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srs)

# The visual language, unchanged from the combined report:
#   bronze process · teal data at rest · plum external service
#   green terminal success · red terminal failure · dashed conditional
esc = srs.esc
box, cyl, para, actor, ellipse, diamond, svg = (
    srs.box, srs.cyl, srs.para, srs.actor, srs.ellipse, srs.diamond, srs.svg)
BRONZE, TEAL, PLUM = srs.BRONZE, srs.TEAL, srs.PLUM
GREEN, RED, AMBER = srs.GREEN, srs.RED, srs.AMBER
INK, INK2, INK3, RULE = srs.INK, srs.INK2, srs.INK3, srs.RULE


def arrow(x1, y1, x2, y2, cls="ln", label="", dash=False, lx=None, ly=None):
    """Straight connector with an optional label at its midpoint."""
    c = cls + (" dash" if dash else "")
    out = f'<path class="{c}" d="M{x1},{y1} L{x2},{y2}"/>'
    if label:
        out += (f'<text class="lbc" x="{lx if lx is not None else (x1+x2)/2}" '
                f'y="{ly if ly is not None else (y1+y2)/2 - 6}">{esc(label)}</text>')
    return out


def elbow(pts, cls="ln", label="", dash=False, lx=None, ly=None):
    """Orthogonal connector through a list of points."""
    c = cls + (" dash" if dash else "")
    d = f'M{pts[0][0]},{pts[0][1]} ' + " ".join(f"L{x},{y}" for x, y in pts[1:])
    out = f'<path class="{c}" d="{d}"/>'
    if label and lx is not None:
        out += f'<text class="lbc" x="{lx}" y="{ly}">{esc(label)}</text>'
    return out


def band(x, y, w, h, label, colour=None):
    """A labelled boundary the diagram's own system sits inside."""
    out = f'<rect class="band" x="{x}" y="{y}" width="{w}" height="{h}" rx="14"/>'
    out += (f'<text class="cap" x="{x+w/2}" y="{y+20}" '
            f'fill="{colour or BRONZE}">{esc(label)}</text>')
    return out


def lane(x, y, w, h, title, colour=INK3):
    """A swimlane header plus its column rule."""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#fcfbf8" '
            f'stroke="{RULE}" stroke-width="1"/>'
            f'<text class="cap" x="{x+w/2}" y="{y+19}" fill="{colour}">{esc(title)}</text>')


def note(x, y, text, colour=INK3):
    """A small annotation, wrapped by the caller into separate lines."""
    lines = text if isinstance(text, (list, tuple)) else [text]
    out = ""
    for i, ln in enumerate(lines):
        out += f'<text class="lb" x="{x}" y="{y + i*13}" fill="{colour}">{esc(ln)}</text>'
    return out


def lifeline(x, top, bottom, label, kind="proc"):
    """Sequence-diagram participant: a head box and a dashed life line."""
    w, h = 132, 34
    out = box(x - w / 2, top, w, h, label, cls=kind)
    out += (f'<path d="M{x},{top+h} L{x},{bottom}" stroke="{INK3}" stroke-width="1" '
            f'stroke-dasharray="3 4" fill="none"/>')
    return out


def msg(x1, x2, y, label, cls="ln", dash=False):
    """A sequence-diagram message. Label sits above the line, centred."""
    c = cls + (" dash" if dash else "")
    out = f'<path class="{c}" d="M{x1},{y} L{x2},{y}"/>'
    out += f'<text class="lbc" x="{(x1+x2)/2}" y="{y-6}">{esc(label)}</text>'
    return out


def selfmsg(x, y, label, w=54):
    out = (f'<path class="ln" d="M{x},{y} L{x+w},{y} L{x+w},{y+20} L{x+4},{y+20}"/>')
    out += f'<text class="lb" x="{x+w+8}" y="{y+14}">{esc(label)}</text>'
    return out


def activation(x, y, h, colour=BRONZE):
    return (f'<rect x="{x-5}" y="{y}" width="10" height="{h}" fill="#fff" '
            f'stroke="{colour}" stroke-width="1.2"/>')


def entity(x, y, w, title, fields, pk=None):
    """ER box: a title bar and a list of columns."""
    rows = len(fields)
    h = 26 + rows * 15 + 8
    out = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="#fff" '
           f'stroke="{TEAL}" stroke-width="1.5"/>')
    out += (f'<path d="M{x},{y+26} h{w}" stroke="{TEAL}" stroke-width="1.2" opacity=".5"/>')
    out += f'<text class="tc" x="{x+w/2}" y="{y+18}">{esc(title)}</text>'
    for i, f in enumerate(fields):
        mark = "PK" if f == pk else ("FK" if f.endswith("_id") and f != pk else "")
        out += f'<text class="lb" x="{x+10}" y="{y+42+i*15}">{esc(f)}</text>'
        if mark:
            out += (f'<text class="lb" x="{x+w-10}" y="{y+42+i*15}" '
                    f'text-anchor="end" fill="{BRONZE}">{mark}</text>')
    return out, h


def legend(x, y, items):
    """Key strip: (colour, shape-hint, label) triples laid out in a row."""
    out = ""
    cx = x
    for colour, label in items:
        out += (f'<rect x="{cx}" y="{y}" width="11" height="11" rx="3" fill="#fff" '
                f'stroke="{colour}" stroke-width="1.6"/>')
        out += f'<text class="lb" x="{cx+17}" y="{y+9}">{esc(label)}</text>'
        cx += 22 + len(label) * 5.4
    return out
