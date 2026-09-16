"""A tiny block vocabulary shared by both per-product reports.

Content is written once, here and in the two content modules, and rendered
twice — to HTML by render_html.py and to .docx by render-docx.js via a JSON
dump. Writing it in two places is how the combined report's two formats drifted
apart in the first place.
"""


def P(text):
    return {"k": "p", "text": text}


def H3(text):
    return {"k": "h3", "text": text}


def H4(text):
    return {"k": "h4", "text": text}


def LEDE(text):
    return {"k": "lede", "text": text}


def UL(*items):
    return {"k": "ul", "items": list(items)}


def TBL(headers, rows, widths=None):
    return {"k": "tbl", "headers": headers, "rows": rows, "widths": widths}


def NOTE(label, text, tone="teal"):
    return {"k": "note", "label": label, "text": text, "tone": tone}


def STATS(*pairs):
    """(value, key, footnote) triples — the big-number strip."""
    return {"k": "stats", "items": [list(p) for p in pairs]}


def FIG(fid, title, caption, src, w=880, h=500):
    """A figure carried as a rasterised PNG plus its SVG for the HTML."""
    return {"k": "fig", "id": fid, "title": title, "caption": caption,
            "src": src, "w": w, "h": h}


def CODE(text):
    return {"k": "code", "text": text}


def CH(num, title, lede, *blocks):
    return {"num": num, "title": title, "lede": lede, "blocks": list(blocks)}
