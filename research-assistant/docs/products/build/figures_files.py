"""The nine SRS diagrams for Chat with Files, drawn for this product alone.

Two paths run through almost every diagram here and they are deliberately kept
apart: ingestion, which happens once per document and asynchronously, and
answering, which happens per question and synchronously. Conflating them is the
most common way to misread this product.
"""
from common import (esc, box, cyl, para, actor, ellipse, diamond, svg, arrow,
                    elbow, band, note, lifeline, msg, selfmsg, activation,
                    entity, legend, BRONZE, TEAL, PLUM, GREEN, RED, AMBER,
                    INK, INK2, INK3, RULE)


# ------------------------------------------------------------------ F.1
def f1():
    """Context diagram — the product, its actor, and the systems around it."""
    b = actor(72, 176, "Document owner")
    b += band(200, 110, 300, 150, "CHAT WITH FILES")
    b += box(232, 148, 236, 82, "Cognita", "ingest · retrieve · answer", rx=10)

    ext = [(600, 44, "Groq inference", "answering, grading, judge"),
           (600, 128, "Supabase auth", "JWT via public JWKS"),
           (600, 212, "Stripe", "subscription state")]
    for x, y, label, sub in ext:
        b += para(x, y, 230, 54, label, sub)

    b += arrow(148, 170, 226, 170, "lnb", "upload a file", ly=162)
    b += arrow(148, 196, 226, 196, "lnb", "ask a question", ly=214)
    # Routed round the outside: every inner lane is occupied by a forward arrow
    # or its label, and the actor's caption sits at y 216-227.
    b += elbow([(300, 232), (300, 268), (14, 268), (14, 190), (56, 190)],
               "ln", dash=True,
               label="answer with the passages it used, or a refusal",
               lx=176, ly=262)

    for _, y, _, _ in ext:
        b += arrow(470, 189, 596, y + 27, "lnp")

    b += cyl(232, 292, 236, 56, "Postgres + pgvector", "documents, chunks, chats")
    b += arrow(350, 230, 350, 290, "lnt")

    b += note(524, 292, ["Embeddings are computed on the application",
                         "node, not by a provider — no vector data",
                         "leaves the deployment."])
    b += legend(200, 372, [(BRONZE, "this product"), (PLUM, "outside the boundary"),
                           (TEAL, "data at rest")])
    return svg(880, 400, b)


# ------------------------------------------------------------------ F.2
def f2():
    """DFD level 0 — the two paths, kept visually apart."""
    b = para(40, 60, 158, 54, "Document owner", "uploads a file")
    b += para(40, 220, 158, 54, "Document owner", "asks a question")

    b += box(300, 50, 250, 76, "1.0  Ingest", "extract · chunk · embed", rx=12)
    b += box(300, 210, 250, 76, "2.0  Answer", "retrieve · grade · reply", rx=12)

    b += arrow(200, 86, 296, 86, "lnb", "file bytes", ly=78)
    b += arrow(200, 246, 296, 246, "lnb", "question", ly=238)
    b += elbow([(296, 276), (250, 276), (250, 320), (119, 320), (119, 280)],
               "ln", dash=True)
    b += note(70, 340, ["answer + passages, or a refusal"])

    b += para(676, 210, 168, 54, "Groq", "inference")
    b += arrow(552, 240, 672, 238, "lnp")
    b += note(580, 224, ["prompts"])

    b += cyl(624, 50, 200, 58, "D1  rag_documents", "status + metadata")
    b += cyl(624, 128, 200, 58, "D2  rag_chunks", "text + 384-d vector")
    b += arrow(552, 76, 620, 76, "lnt")
    b += arrow(552, 100, 620, 150, "lnt")
    b += elbow([(700, 186), (700, 198), (620, 198), (620, 232), (552, 232)],
               "lnt", dash=True)
    b += note(560, 300, ["retrieval reads chunks only;", "the answer never sees a whole file"])

    b += cyl(300, 320, 250, 54, "D3  rag_conversations + rag_messages", "")
    b += arrow(425, 288, 425, 316, "lnt")

    b += legend(40, 402, [(BRONZE, "process"), (TEAL, "data store"),
                          (PLUM, "external entity"), (INK3, "dashed = conditional")])
    return svg(880, 430, b)


# ------------------------------------------------------------------ F.3
def f3():
    """DFD level 1 — ingestion above, answering below, numbered separately."""
    def caption(x, y, text, colour):
        return (f'<text x="{x}" y="{y}" font-family="JetBrains Mono,monospace" '
                f'font-size="9" letter-spacing=".1em" fill="{colour}">{esc(text)}</text>')

    b = caption(24, 26, "INGESTION - ONCE PER DOCUMENT, ASYNCHRONOUS", BRONZE)
    b += para(24, 52, 118, 48, "Owner", "")
    ing = [(170, "1.1 Validate", "magic bytes"),
           (330, "1.2 Extract", "PDF · DOCX · OCR"),
           (490, "1.3 Chunk", "1,000 / 150 overlap"),
           (650, "1.4 Embed", "bge-small, local")]
    for x, label, sub in ing:
        b += box(x, 44, 146, 58, label, sub)
    b += arrow(142, 72, 166, 72, "lnb")
    for i in range(3):
        b += arrow(ing[i][0] + 146, 73, ing[i + 1][0], 73, "lnb")

    b += cyl(400, 140, 190, 52, "D1 rag_documents", "")
    b += cyl(650, 140, 190, 52, "D2 rag_chunks", "")
    b += arrow(723, 102, 723, 136, "lnt")
    b += elbow([(403, 102), (403, 120), (495, 120), (495, 136)], "lnt")
    b += note(150, 150, ["the HTTP request returns", "as soon as the row exists"])

    b += f'<path d="M24,214 L856,214" stroke="{RULE}" stroke-width="1.2"/>'
    b += caption(24, 242, "ANSWERING - ONCE PER QUESTION, SYNCHRONOUS", TEAL)

    b += para(24, 268, 118, 48, "Owner", "")
    top = [(170, "2.1 Contextualise", "resolve pronouns"),
           (330, "2.2 Retrieve", "vector + keyword"),
           (490, "2.3 Fuse", "RRF, k = 60"),
           (650, "2.4 Grade", "do these answer it?")]
    for x, label, sub in top:
        b += box(x, 260, 146, 58, label, sub)
    b += box(490, 356, 146, 58, "2.5 Rewrite", "different wording")
    b += box(650, 356, 146, 58, "2.6 Answer", "or decline")

    b += arrow(142, 288, 166, 288, "lnb")
    for i in range(3):
        b += arrow(top[i][0] + 146, 289, top[i + 1][0], 289, "lnb")

    b += elbow([(723, 318), (723, 336), (563, 336), (563, 356)], "lnb", dash=True)
    b += note(576, 332, ["no - rewrite once"], BRONZE)
    b += arrow(723, 336, 723, 352, "lnb")
    b += note(732, 340, ["yes"], BRONZE)

    b += elbow([(490, 395), (310, 395), (310, 332), (403, 332), (403, 322)], "lnb", dash=True)
    b += note(322, 352, ["retry retrieval, once only"], BRONZE)

    b += elbow([(650, 166), (610, 166), (610, 232), (403, 232), (403, 256)], "lnt")
    b += note(412, 224, ["chunks + vectors"], TEAL)

    b += elbow([(723, 414), (723, 448), (120, 448), (120, 322)], "ln", dash=True)
    b += note(330, 464, ["answer with the passages it used, or a refusal"])

    b += legend(24, 492, [(BRONZE, "process"), (TEAL, "store"),
                          (PLUM, "external"), (INK3, "dashed = conditional")])
    return svg(880, 520, b)


# ------------------------------------------------------------------ F.4
def f4():
    """Use case diagram — what a user can do with this product."""
    b = actor(76, 120, "Document owner")
    b += actor(76, 300, "Guest (dev)")
    b += actor(800, 200, "Stripe")
    b += band(190, 26, 540, 350, "CHAT WITH FILES")

    cases = [(460, 76, "Upload PDF, DOCX, TXT, MD or image"),
             (460, 124, "Watch ingestion progress"),
             (460, 172, "Ask a question of the corpus"),
             (460, 220, "See which passages were used"),
             (460, 268, "Receive an honest refusal"),
             (460, 316, "Delete a document and its chunks"),
             (460, 356, "Consume monthly quota")]
    for cx, cy, label in cases:
        b += ellipse(cx, cy, 168, 18, label)

    for cy in (76, 124, 172, 220, 268, 316):
        b += arrow(112, 130, 290, cy, "ln")
    b += arrow(112, 306, 292, 316, "ln")
    b += elbow([(792, 208), (700, 208), (700, 356), (630, 356)], "lnp")

    b += note(200, 398, ["Answering from the open web is NOT a use case of this product — that belongs to",
                         "Deep Research. Everything here is bounded by what the user uploaded."])
    return svg(880, 430, b)


# ------------------------------------------------------------------ F.5
def f5():
    """Sequence diagram — an upload, then a question over the resulting corpus."""
    TOP, BOT = 26, 620
    X = {"br": 90, "api": 264, "ing": 440, "ex": 618, "pg": 790}
    b = ""
    b += lifeline(X["br"], TOP, BOT, "Browser")
    b += lifeline(X["api"], TOP, BOT, "FastAPI")
    b += lifeline(X["ing"], TOP, BOT, "Ingest / retrieval")
    b += lifeline(X["ex"], TOP, BOT, "Groq", "ext")
    b += lifeline(X["pg"], TOP, BOT, "Postgres", "store")

    b += f'<text class="cap" x="120" y="102" fill="{BRONZE}">UPLOAD</text>'
    rows_a = [
        ("br", "api", "POST the file", "ln", False),
        ("api", "pg", "insert row, status = processing", "lnt", False),
        ("api", "br", "202 Accepted — request returns now", "ln", True),
        ("api", "ing", "hand off, out of the request", "lnb", False),
        ("ing", "ing", None, None, None),
        ("ing", "pg", "write chunks + vectors, status = ready", "lnt", False),
    ]
    y = 126
    for a, c, label, cls, dash in rows_a:
        if label is None:
            b += selfmsg(X["ing"] + 6, y, "extract, chunk, embed locally")
            y += 44
            continue
        x1, x2 = X[a], X[c]
        b += msg(x1 + (6 if x2 > x1 else -6), x2 + (-6 if x2 > x1 else 6), y, label, cls, dash)
        y += 30

    y += 14
    b += f'<path d="M24,{y-8} L856,{y-8}" stroke="{RULE}" stroke-width="1.2"/>'
    b += f'<text class="cap" x="126" y="{y+18}" fill="{TEAL}">QUESTION</text>'
    y += 40
    rows_b = [
        ("br", "api", "POST the question", "ln", False),
        ("api", "ing", "contextualise against chat history", "lnb", False),
        ("ing", "pg", "vector search + keyword search", "lnt", False),
        ("ing", "ing", None, None, None),
        ("ing", "ex", "grade the passages  (20B)", "lnp", False),
        ("ing", "ex", "answer from the passages  (120B)", "lnp", False),
        ("ing", "pg", "persist the turn", "lnt", False),
        ("api", "br", "answer + the passages it used", "ln", False),
    ]
    for a, c, label, cls, dash in rows_b:
        if label is None:
            b += selfmsg(X["ing"] + 6, y, "fuse the two rankings — RRF")
            y += 44
            continue
        x1, x2 = X[a], X[c]
        b += msg(x1 + (6 if x2 > x1 else -6), x2 + (-6 if x2 > x1 else 6), y, label, cls, dash)
        y += 30

    b += note(24, 650, ["If grading fails, the question is rewritten once and retrieval runs again before the",
                        "system declines — that branch is drawn in full in Figure F.9."])
    return svg(880, 686, b)


# ------------------------------------------------------------------ F.6
def f6():
    """Entity-relationship diagram — the corpus and the conversations over it.

    Column names are the real ones, read from backend/rag/store.py and the
    hybrid-search migration. There is no users table: identity is delegated to
    Supabase, so user_id is a subject claim from a verified JWT.
    """
    b = para(30, 60, 170, 50, "Supabase identity", "user_id from a JWT")

    e1, h1 = entity(250, 44, 230, "rag_documents",
                    ["id", "user_id", "filename", "file_type", "status",
                     "char_count", "chunk_count", "error", "created_at"], pk="id")
    e2, h2 = entity(560, 44, 250, "rag_chunks",
                    ["id", "document_id", "chunk_index", "content",
                     "embedding  vector(384)", "content_tsv  tsvector"], pk="id")
    e3, h3 = entity(250, 252, 230, "rag_conversations",
                    ["id", "user_id", "created_at"], pk="id")
    e4, h4 = entity(560, 252, 250, "rag_messages",
                    ["id", "conversation_id", "role", "content",
                     "sources  (JSON text)", "created_at"], pk="id")
    b += e1 + e2 + e3 + e4

    b += arrow(480, 80, 556, 80, "lnt")
    b += note(496, 72, ["1 : N"], TEAL)
    b += arrow(480, 288, 556, 288, "lnt")
    b += note(496, 280, ["1 : N"], TEAL)
    b += elbow([(200, 84), (225, 84), (225, 80), (246, 80)], "lnt")
    b += elbow([(200, 96), (225, 96), (225, 288), (246, 288)], "lnt")
    b += note(206, 200, ["1 : N"], TEAL)

    b += note(30, 132, ["No local users", "table — identity", "lives in Supabase"])

    b += note(30, 372,
              ["rag_chunks and rag_messages carry no user_id of their own. Their row-level security policies",
               "are derived — a chunk is visible only if its parent document is, and a message only if its",
               "conversation is. One fewer column to forget on insert, and no way for a chunk and its document",
               "to disagree about who owns them. Both foreign keys are ON DELETE CASCADE.",
               "",
               "embedding is vector(384) behind an HNSW index; content_tsv is a generated tsvector behind a GIN",
               "index. Both halves of hybrid retrieval are indexed on the same row, so fusion needs no join."])
    b += legend(30, 470, [(TEAL, "entity and relationship"), (BRONZE, "key column"),
                          (PLUM, "outside the boundary")])
    return svg(880, 498, b)


# ------------------------------------------------------------------ F.7
def f7():
    """State transition diagram — the life of one uploaded document."""
    b = f'<circle cx="60" cy="86" r="9" fill="{INK}"/>'
    b += arrow(69, 86, 116, 86, "lnb")
    b += box(120, 60, 160, 52, "uploaded", "row exists")
    b += arrow(280, 86, 326, 86, "lnb")
    b += box(330, 60, 160, 52, "extracting", "by type")
    b += arrow(490, 86, 536, 86, "lnb")
    b += box(540, 60, 160, 52, "chunking", "1,000 / 150")
    b += elbow([(620, 112), (620, 150), (200, 150), (200, 186)], "lnb")
    b += box(120, 186, 160, 52, "embedding", "local, 384-d")
    b += arrow(280, 212, 326, 212, "lnb")
    b += box(330, 186, 180, 52, "ready", "answerable", cls="ok")

    b += box(330, 316, 180, 52, "failed", "unsupported or corrupt", cls="bad")
    b += elbow([(410, 112), (410, 130), (300, 130), (300, 342), (326, 342)],
               "lnb", dash=True)
    b += note(214, 300, ["any ingest step,", "on error"], RED)

    b += box(600, 316, 200, 52, "failed (stale)", "reaped after 15 min", cls="bad")
    b += elbow([(200, 238), (200, 280), (700, 280), (700, 312)], "lnb", dash=True)
    b += note(360, 274, ["process restarted mid-ingest"], AMBER)

    b += box(600, 186, 200, 52, "deleted", "chunks cascade", cls="ok")
    b += arrow(510, 212, 596, 212, "lnb", "on request", ly=204)

    b += note(120, 396,
              ["There is no durable queue behind this. A restart between 'uploaded' and 'ready'",
               "strands the row, and the reaper is what stops it sitting in 'processing' forever —",
               "a mitigation, not a fix. Chapter 10 says so plainly."])
    b += legend(120, 456, [(BRONZE, "in progress"), (GREEN, "terminal success"),
                           (RED, "terminal failure"), (INK3, "dashed = conditional")])
    return svg(880, 484, b)


# ------------------------------------------------------------------ F.8
def f8():
    """Deployment diagram — where this product's work physically runs."""
    b = band(30, 30, 240, 190, "CLIENT")
    b += box(56, 66, 188, 54, "Browser", "React 19 SPA")
    b += box(56, 138, 188, 54, "Upload widget", "progress polling")

    b += band(310, 30, 270, 300, "APPLICATION NODE")
    b += box(336, 66, 218, 54, "uvicorn / FastAPI", "async workers")
    b += box(336, 138, 218, 54, "fastembed", "bge-small, in-process")
    b += box(336, 210, 218, 54, "ingest task", "background, same process")

    b += band(620, 30, 230, 176, "DATA NODE")
    b += cyl(646, 66, 178, 62, "PostgreSQL 16", "pgvector + FTS")
    b += note(646, 150, ["HNSW on embedding", "GIN on tsv"])

    b += band(620, 240, 230, 186, "EXTERNAL")
    b += para(646, 272, 178, 48, "Groq", "20B / 120B")
    b += para(646, 332, 178, 48, "Supabase", "JWKS")

    b += arrow(248, 92, 332, 92, "ln", "HTTPS")
    b += arrow(248, 164, 332, 100, "ln")
    b += arrow(558, 96, 642, 96, "lnt", "cognita_app role")
    b += arrow(558, 236, 642, 100, "lnt")
    b += arrow(558, 164, 642, 296, "lnp")

    b += note(336, 290, ["embedding runs here, so retrieval costs nothing",
                         "and evaluating hundreds of questions is free"])
    b += note(336, 352, ["ingestion shares the web process — the single",
                         "largest architectural compromise in this product"], AMBER)
    return svg(880, 452, b)


# ------------------------------------------------------------------ F.9
def f9():
    """Activity diagram — grade, rewrite, retry, decline."""
    b = f'<circle cx="150" cy="40" r="9" fill="{INK}"/>'
    b += arrow(150, 49, 150, 72, "lnb")
    b += box(60, 72, 180, 46, "Contextualise", "resolve against history")
    b += arrow(150, 118, 150, 146, "lnb")
    b += box(60, 146, 180, 46, "Vector search", "cosine, top 20")
    b += arrow(150, 192, 150, 220, "lnb")
    b += box(60, 220, 180, 46, "Keyword search", "websearch_to_tsquery")
    b += arrow(150, 266, 150, 294, "lnb")
    b += box(60, 294, 180, 46, "Fuse rankings", "RRF, k = 60")
    b += arrow(240, 317, 344, 317, "lnb")
    b += box(350, 294, 190, 46, "Grade the passages")
    b += arrow(400, 294, 422, 246, "lnb")
    b += diamond(450, 220, 200, 62, "do they answer it?")

    b += arrow(550, 220, 634, 220, "lnb")
    b += note(576, 212, ["yes"], BRONZE)
    b += box(640, 196, 190, 48, "Answer from them", "with citations", cls="ok")
    b += arrow(735, 196, 735, 160, "lnb")
    b += box(640, 104, 190, 48, "Judge the answer", "faithful? relevant?")
    b += arrow(735, 104, 735, 68, "lnt")
    b += f'<circle cx="735" cy="50" r="11" fill="none" stroke="{INK}" stroke-width="2"/>'
    b += f'<circle cx="735" cy="50" r="6" fill="{INK}"/>'

    b += elbow([(350, 220), (300, 220), (300, 404), (344, 404)], "lnb", dash=True)
    b += note(252, 284, ["no - and no", "retry yet"], BRONZE)
    b += box(350, 380, 190, 48, "Rewrite the question", "different wording")
    b += elbow([(445, 428), (445, 466), (150, 466), (150, 346)], "lnb", dash=True)
    b += note(300, 484, ["retry retrieval, once only"])

    b += elbow([(480, 244), (600, 244), (600, 404), (634, 404)], "lnb", dash=True)
    b += note(608, 330, ["no - and", "already retried"], BRONZE)
    b += box(640, 380, 190, 48, "Decline to answer", "say what is missing", cls="ok")

    b += note(60, 520,
              ["Declining is drawn as a success because that is what it is. A system that answers",
               "every question from a corpus that does not contain the answer is not more useful —",
               "it is the failure this product exists to avoid."])
    return svg(880, 566, b)


FIGURES = [
    ("F.1", "Context diagram", f1,
     "Chat with Files and everything outside it. Embeddings are computed locally, so no vector data leaves the deployment."),
    ("F.2", "Data flow diagram — level 0", f2,
     "Two processes, not one: ingestion runs per document and asynchronously, answering runs per question and synchronously."),
    ("F.3", "Data flow diagram — level 1", f3,
     "Both paths decomposed. The dashed edge from grading back to rewriting is what turns retrieval from one shot into a loop."),
    ("F.4", "Use case diagram", f4,
     "Everything a user can do with this product. Searching the web is deliberately absent — that belongs to Deep Research."),
    ("F.5", "Sequence diagram — upload, then ask", f5,
     "The upload returns before the work finishes; the question does not. The split is the reason the two halves are drawn apart."),
    ("F.6", "Entity-relationship diagram", f6,
     "Chunks and messages carry no user id — their access policies are derived from the parent row, so the two cannot disagree."),
    ("F.7", "State transition diagram", f7,
     "The life of one uploaded document, including the stale state a restart produces and the reaper that ends it."),
    ("F.8", "Deployment diagram", f8,
     "Embedding runs in the application process, which is what makes evaluation free — and ingestion shares it, which is the compromise."),
    ("F.9", "Activity diagram", f9,
     "Grade, rewrite, retry, decline. Declining is drawn as a terminal success, because it is one."),
]
