"""Drawing primitives for the two per-product reports.

Everything comes from draw.py, which is written in Cognita's own design tokens.
Both reports use one theme and one visual language: the legend says "process",
"data store", "external", and those meanings must not change colour between one
document and the other.
"""
from draw import (  # noqa: F401
    esc, svg,
    box, cyl, para, diamond, ellipse, actor, band, lane,
    arrow, elbow, note, chip, legend,
    lifeline, msg, selfmsg, activation, entity,
    TERRACOTTA, TEAL, PLUM, GREEN, RED, AMBER,
    INK, INK2, INK3, RULE, BG_APP, BG_CARD,
)

# The figure modules were written against the earlier palette's name for the
# accent. Kept as an alias rather than renamed through nine figures apiece.
BRONZE = TERRACOTTA
