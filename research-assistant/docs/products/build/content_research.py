"""Deep Research — the complete report content.

Standalone by design. Where a chapter covers something the platform shares with
Chat with Files (the database, the security model, CI), it is repeated here in
full rather than cross-referenced, because a reader handed only this document
should never need the other one.
"""
from spec import P, H3, H4, LEDE, UL, TBL, NOTE, STATS, FIG, CODE, CH

META = {
    "key": "deep-research",
    "product": "Deep Research",
    "other": "Chat with Files",
    "accent": "bronze",
    "eyebrow": "PRODUCT REPORT · ONE OF TWO",
    "title": "Deep Research",
    "title_em": "an answer you can check",
    "sub": ("The multi-agent pipeline behind Cognita's research tool: how a typed question "
            "becomes a plan, a search, a body of evidence, a verified draft and a confidence "
            "score that reports its own reasoning."),
    "author": "Prince Yadav",
    "date": "16 September 2026",
    "route": "/#research",
}

CHAPTERS = [

    # ------------------------------------------------------------------ 1
    CH(1, "Introduction and Problem Statement",
       "A language model asked a research question will produce a fluent, confident, "
       "well-structured answer whether or not it has any basis for it. The failure is not "
       "that it is sometimes wrong; it is that a wrong answer is indistinguishable from a "
       "right one.",

       H3("1.1 The problem"),
       P("Retrieval-augmented generation is the usual response: give the model source documents "
         "and instruct it to answer from them. This helps, but it moves the problem rather than "
         "solving it. The model can still assert things the sources do not support, cite a "
         "document that does not contain the claim, or answer a question the sources never "
         "addressed. A reader has no way to tell which happened."),
       P("Deep Research starts from a different premise: a research tool's output is only as "
         "valuable as the reader's ability to check it. Three properties follow, and everything "
         "in this document is downstream of them."),
       UL("Every claim traces to a source. Citations must resolve to a document the system "
          "actually read, and that must be verified in code rather than trusted.",
          "Verification must be independent. Checking a claim against the same text it was "
          "summarised from proves only that the summary was faithful.",
          "Confidence must be honest. A score that does not reflect the quality of the evidence "
          "beneath it is decoration, and worse than no score at all."),

       H3("1.2 What this product is"),
       P("Deep Research is one of the two products in Cognita. A user types a question at "
         "/#research and nothing else. The system decomposes it into sub-queries, searches the "
         "open web, fetches and extracts the pages it finds, optionally folds in documents the "
         "user has uploaded, synthesises a draft, verifies each claim in that draft against "
         "sources it searches for separately, decides whether the evidence is sufficient, and "
         "either returns to searching or writes the report."),
       P("The output is a cited document with a confidence score and a breakdown of what limits "
         "that score. Progress streams to the browser over a WebSocket while the run is in "
         "flight, which is what the live pipeline animation in the interface is driven by."),

       H3("1.3 What this product is not"),
       P("Cognita's other product, Chat with Files, answers questions from documents the user "
         "uploads. It is a separate page with its own query box, its own retrieval path and its "
         "own benchmark. It is not a stage of the pipeline described here, and this document "
         "does not describe it."),
       P("The two products meet at exactly one place. The corpus node in this pipeline can read "
         "the chunks that Chat with Files created, so a research run can draw on the user's own "
         "documents as well as the web. That is Deep Research borrowing the other product's "
         "store. The borrowing is one-way: nothing in this pipeline writes to it."),
       NOTE("Why they are documented separately.",
            "The two products share a database, an authentication model and a deployment, and "
            "almost nothing else. Reading about a nine-node agent graph and a chunking strategy "
            "in one narrative makes both harder to follow, and invites the specific "
            "misunderstanding that the second is a component of the first.", "bronze"),

       H3("1.4 What this report covers"),
       P("Chapters 2 to 8 describe requirements, architecture, implementation and security for "
         "this product alone. Chapter 9 reports measurements taken from the running system — "
         "every figure in it was produced by executing the software, not estimated. Chapter 10 "
         "states plainly what remains unproven. Chapter 11 carries the nine SRS diagrams, drawn "
         "for this product rather than for Cognita as a whole, and Chapter 12 reproduces every "
         "prompt this pipeline sends.")),

    # ------------------------------------------------------------------ 2
    CH(2, "Software Requirements Specification",
       "The requirements this product is built against, separated from those of Chat with "
       "Files so that each can be read, tested and argued with on its own terms.",

       H3("2.1 Purpose and intended audience"),
       P("This specification describes the research half of a web application delivering "
         "verifiable answers. Its users are researchers, analysts and students who need an "
         "answer they can defend, not merely an answer they can read. Its secondary audience is "
         "whoever maintains the pipeline: every requirement below is stated so that a test can "
         "be written against it."),

       H3("2.2 Functional requirements"),
       TBL(["ID", "Requirement", "Priority", "Status"], [
           ["DR-1", "Accept a natural-language research question of up to 500 characters.", "Must", "Implemented"],
           ["DR-2", "Classify question complexity and scale research depth accordingly.", "Should", "Implemented"],
           ["DR-3", "Route a non-research message to a direct reply without running the pipeline.", "Should", "Implemented"],
           ["DR-4", "Decompose a question into 3–5 targeted sub-queries before searching.", "Must", "Implemented"],
           ["DR-5", "Search the open web and extract full text from HTML and PDF sources.", "Must", "Implemented"],
           ["DR-6", "Deduplicate results by normalised URL before reading.", "Must", "Implemented"],
           ["DR-7", "Disclose when a source degraded to a search snippet rather than full text.", "Must", "Implemented"],
           ["DR-8", "Search the user's uploaded documents as part of the same evidence set.", "Must", "Implemented"],
           ["DR-9", "Reserve evidence slots for corpus chunks so uploads cannot be crowded out.", "Should", "Implemented"],
           ["DR-10", "Extract key factual claims from the draft and verify each against evidence.", "Must", "Implemented"],
           ["DR-11", "Corroborate each claim against sources the draft was not written from.", "Must", "Implemented"],
           ["DR-12", "Select verification evidence by relevance to the claim, not by position.", "Must", "Implemented"],
           ["DR-13", "Re-search when gap analysis finds the evidence insufficient.", "Should", "Implemented"],
           ["DR-14", "Bound the number of research iterations so a run cannot loop indefinitely.", "Must", "Implemented"],
           ["DR-15", "Validate that every citation resolves to a source actually read.", "Must", "Implemented"],
           ["DR-16", "Report a confidence score together with the factors that produced it.", "Must", "Implemented"],
           ["DR-17", "Stream progress and the report itself as they are produced.", "Should", "Implemented"],
           ["DR-18", "Export a report as Markdown, BibTeX and PDF.", "Should", "Implemented"],
           ["DR-19", "Enforce a monthly query allowance, refunding the quota when a run fails.", "Must", "Implemented"],
           ["DR-20", "Delete all of a user's research history on request (GDPR erasure).", "Must", "Implemented"],
       ], [0.09, 0.58, 0.13, 0.20]),

       H3("2.3 Non-functional requirements"),
       TBL(["ID", "Category", "Requirement", "Verified by"], [
           ["DN-1", "Security", "One tenant's research history must be unreachable by another, enforced at the database.", "CI gate, verify_rls.py"],
           ["DN-2", "Security", "Fetched page content must not be able to alter system behaviour.", "Structural delimiting"],
           ["DN-3", "Security", "Credentials and API keys must never appear in logs.", "Code review, _safe_url"],
           ["DN-4", "Correctness", "A run with no extractable claims must score 0.0, not a default.", "Unit test"],
           ["DN-5", "Correctness", "An unsupported claim must not be averaged away by supported ones.", "Unit test"],
           ["DN-6", "Reliability", "Transient provider failures must be retried; permanent ones must not.", "26 unit tests"],
           ["DN-7", "Reliability", "A failed run must refund the quota it consumed.", "Code path only — untested"],
           ["DN-8", "Performance", "Claim verification must not dominate run time.", "Batched: 257 s → one call"],
           ["DN-9", "Accessibility", "WCAG 2.1 AA contrast; visible keyboard focus; 44 px touch targets.", "Measured in browser"],
           ["DN-10", "Observability", "Token usage and cost must be recorded per research run.", "Persisted per session"],
           ["DN-11", "Portability", "Schema changes applied by versioned migrations, never at startup.", "Alembic, 4 revisions"],
       ], [0.09, 0.14, 0.50, 0.27]),

       H3("2.4 Constraints"),
       UL("Postgres only. The corpus node reads pgvector chunks and every table carries a "
          "row-level security policy; SQLite is rejected at startup.",
          "Free-tier inference. Groq's limits — 8,000 tokens per minute and 200,000 per day — "
          "shape batching, retry behaviour and model allocation throughout this pipeline.",
          "Two database roles. An owner role for migrations and the payment webhook path, a "
          "low-privilege role for everything at runtime, or row-level security has no effect.",
          "One process. The pipeline runs in the web process; there is no worker fleet and no "
          "durable queue behind it."),

       H3("2.5 Assumptions and dependencies"),
       UL("The search provider returns results for arbitrary natural-language sub-queries.",
          "Fetched pages are frequently unreadable — paywalls, JavaScript rendering, bot walls "
          "— so a snippet fallback is a normal path, not an error path.",
          "The inference provider intermittently rejects its own valid structured output, so "
          "every structured call needs a JSON fallback.",
          "Identity is delegated to Supabase; the backend holds no authentication secret and "
          "verifies JWTs against a public JWKS endpoint.")),

    # ------------------------------------------------------------------ 3
    CH(3, "System Architecture",
       "Three tiers: a React single-page application, a FastAPI service hosting a LangGraph "
       "state machine, and Postgres holding both relational and vector data. This chapter "
       "describes them as they serve this product.",

       FIG("3.1", "Deep Research, tier by tier",
           "What each layer is made of and the order one typed question touches it. The "
           "deployment diagram in Chapter 11 says where these processes physically run; this "
           "one says what they are.",
           "fig-r0.png", 880, 494),

       H3("3.1 Why a graph and not a chain"),
       P("The single structural decision that shapes this product is that the pipeline must be "
         "able to go backwards. When the fact-checker finds that most of a draft's claims have "
         "no supporting evidence, the correct response is not to lower a number and ship — it is "
         "to search again with better-targeted queries. A chain of steps cannot express that. A "
         "directed graph with conditional edges can, and LangGraph is a thin enough runtime over "
         "that idea to be worth the dependency."),

       H3("3.2 Technology decisions and their reasons"),
       TBL(["Layer", "Choice", "Why this rather than the obvious alternative"], [
           ["Orchestration", "LangGraph", "The pipeline needs to loop back when evidence is thin. A chain cannot; a graph with conditional edges can."],
           ["Transport", "WebSocket", "A research run takes tens of seconds. Polling would either hide progress or hammer the server; SSE cannot carry the client's cancel."],
           ["Inference", "Groq", "Fast and free at this scale. Two model sizes let structural JSON tasks avoid competing with synthesis for a scarce token budget."],
           ["Corpus access", "pgvector", "The user's documents already live in the same database as their research history, so one policy protects both."],
           ["Identity", "Supabase", "JWTs verified against a public JWKS endpoint, so the backend holds no auth secret."],
           ["Persistence", "PostgreSQL 16", "Row-level security is the second line of tenant isolation, and it only exists in a real database."],
       ], [0.16, 0.16, 0.68]),

       H3("3.3 Model allocation"),
       P("Two model sizes are used deliberately, not incidentally. Structural work — classifying "
         "a question, emitting a JSON list of sub-queries, deciding whether to loop — goes to the "
         "20B model. Synthesis and verification, where quality is the product, go to the 120B "
         "model. On a free tier with a 200,000-token daily ceiling, spending the large model's "
         "budget on a three-way classification is the difference between a system that runs all "
         "day and one that stops at lunchtime."),
       TBL(["Node", "Model", "Why"], [
           ["Triage", "gpt-oss-20b", "A three-way classification. Accuracy here is cheap to reach."],
           ["Planner", "gpt-oss-20b", "Structured output; the task is decomposition, not judgement."],
           ["Analyst", "gpt-oss-120b", "Synthesis across dozens of sources is the quality-critical step."],
           ["Fact-checker", "gpt-oss-120b", "Verification decides the confidence score; a weak model here makes the score meaningless."],
           ["Gap analysis", "gpt-oss-20b", "A binary decision plus a short list of follow-up queries."],
           ["Report", "gpt-oss-120b", "Prose quality is what the user reads."],
       ], [0.22, 0.22, 0.56]),
       NOTE("One pinned model, on purpose.",
            "The model identifiers above are pinned in config.py rather than resolved from a "
            "provider default. The account this project runs on does not expose the llama-3.x "
            "family at all, so a fallback chain that assumed it would fail at runtime on a "
            "machine where it had never been tested.", "bronze")),

    # ------------------------------------------------------------------ 4
    CH(4, "The Agent Pipeline",
       "Nine nodes in a directed graph. The important structural feature is not their number "
       "but the edge that goes backwards: gap analysis can return the run to search when the "
       "evidence gathered so far does not support a confident answer.",

       FIG("4.1", "Research pipeline with reflective loop",
           "Triage routes non-research messages straight to the end. The corpus node folds the "
           "user's own documents into the same evidence set as the web. Gap analysis returns to "
           "search when confidence is low and iterations remain.",
           "fig4-pipeline.png", 860, 240),

       H3("4.1 The nine nodes"),
       TBL(["Node", "Responsibility", "Model", "Design note"], [
           ["Triage", "Classify effort: chat, simple, or deep", "20B", "Without it every question paid the cost of the hardest one. Fails open to deep — over-researching costs time, under-researching costs correctness."],
           ["Planner", "Decompose into 3–5 sub-queries", "20B", "Structured output with a JSON fallback, because the provider's tool-call wrapper intermittently rejects its own valid generation."],
           ["Search", "Execute sub-queries, deduplicate by normalised URL", "—", "Breadth scales with triage: 3 results per query for simple, 5 for deep."],
           ["Reader", "Fetch and extract HTML and PDF, concurrently", "—", "Records when extraction failed and a search snippet was substituted, so the report can disclose it."],
           ["Corpus", "Retrieve from the user's own documents", "—", "Runs even when web search returned nothing — the answer may be in the user's files."],
           ["Analyst", "Synthesise a draft across all evidence", "120B", "Chunks are ranked by relevance; corpus chunks hold reserved slots so deliberately uploaded documents cannot be crowded out."],
           ["Fact-checker", "Extract claims, verify, corroborate independently", "120B", "All claims in one call with per-claim evidence — verifying individually previously consumed 257 s of a 361 s run."],
           ["Gap analysis", "Decide whether to loop or report", "20B", "Hard iteration ceiling prevents unbounded loops; generates targeted follow-up queries."],
           ["Report", "Compose the final document", "120B", "Sources and the confidence block are assembled in code, not generated — removing a place a reference could be invented."],
       ], [0.13, 0.24, 0.08, 0.55]),

       H3("4.2 Triage, and the cost of not having it"),
       P("Before triage existed, every message ran the full pipeline. \"Thanks, that's helpful\" "
         "triggered five web searches. Triage classifies each message into chat, simple or deep, "
         "and the first of those returns a direct reply without touching the graph at all."),
       P("It fails open to deep. A question wrongly classified as simple gets a thin answer and "
         "the user cannot tell why; a question wrongly classified as deep costs time and tokens "
         "and still answers correctly. Those failures are not symmetric, so the default is not "
         "either."),

       H3("4.3 The reflective loop"),
       P("Gap analysis is the conditional edge. It receives the verified claims and the "
         "confidence aggregate, and answers one question: is this enough? If not, and iterations "
         "remain, it emits targeted follow-up queries and the graph returns to the search node "
         "with them. The evidence set accumulates across iterations rather than being replaced."),
       P("The ceiling is hard and low. An unbounded loop against a free-tier provider is not a "
         "quality feature, it is a way to exhaust a daily token budget on one question. When the "
         "ceiling is reached the run reports what it has, with a score that reflects the thinness "
         "of the evidence rather than hiding it."),
       NOTE("This is the structural claim of the product.",
            "Everything else in this pipeline — planning, reading, verification, scoring — exists "
            "in other research tools in some form. The backward edge is what makes the confidence "
            "score actionable rather than decorative: a low score triggers more work instead of "
            "merely being displayed.", "bronze")),

    # ------------------------------------------------------------------ 5
    CH(5, "Evidence Gathering",
       "Four of the nine nodes exist only to assemble the body of evidence a draft is written "
       "from, and a fifth decides which parts of it each claim is checked against. The quality "
       "of the final score is bounded by these steps.",

       H3("5.1 Planning sub-queries"),
       P("A research question is rarely a good search query. The planner decomposes it into "
         "three to five sub-queries that are, each targeting a different facet. This is a "
         "structured-output call: the model returns a JSON list, which is parsed and validated."),
       P("The provider's tool-call wrapper intermittently rejects generations that are in fact "
         "valid JSON, so every structured call in this pipeline carries a plain-text fallback "
         "that re-parses the raw content. A pipeline that fails because a wrapper had an opinion "
         "about its own output is not acceptable at this layer."),

       H3("5.2 Search and deduplication"),
       P("Sub-queries are executed and their results merged. Breadth scales with the triage "
         "classification: three results per sub-query for a simple question, five for a deep "
         "one. Results are deduplicated by normalised URL — tracking parameters stripped, "
         "trailing slashes reconciled — because the same page returned by three sub-queries is "
         "one source, not three, and counting it as three would inflate the source-count caps "
         "that Chapter 6 depends on."),

       H3("5.3 Reading, and the snippet fallback"),
       P("Selected URLs are fetched and extracted concurrently. HTML and PDF are handled "
         "separately. A large fraction of the open web cannot be read by a server-side fetch — "
         "paywalls, JavaScript-rendered content, bot protection — so failure is a normal "
         "outcome, not an exception."),
       P("When extraction fails, the search snippet is substituted and the source is flagged. "
         "That flag travels all the way to the confidence score, where a run whose sources are "
         "mostly snippets is capped at 70%. A search snippet is not the paper it stands for, and "
         "a system that treats the two identically is measuring something other than what it "
         "claims."),

       H3("5.4 The corpus node"),
       P("This is the single point at which Deep Research touches the other product. The corpus "
         "node retrieves from the chunks that Chat with Files created, and folds them into the "
         "same evidence set as the web results."),
       P("It runs even when web search returned nothing, because the answer may be in the user's "
         "own files, and a research tool that ignores the documents its user deliberately "
         "uploaded is failing at the easy case. When the analyst ranks evidence for inclusion, "
         "corpus chunks hold reserved slots — without that, a run with forty web sources would "
         "reliably crowd out the three documents the user cared enough to upload."),

       H3("5.5 Evidence selection for verification"),
       P("Evidence was previously assembled for the fact-checker by position: the first 1,000 "
         "characters of each document, truncated to 6,000 characters overall. On a forty-source "
         "run that is roughly the top of the first six documents. A claim drawn from anywhere "
         "else was unverifiable in principle, and came back \"unverified\" for reasons entirely "
         "unrelated to its truth."),
       P("Passages are now selected per claim, by relevance, across every source. Scoring is "
         "IDF-weighted term overlap computed locally — no API call, no added latency — and the "
         "selector returns at most one passage per source so a single verbose document cannot "
         "monopolise the evidence budget for a claim."),
       NOTE("Why this counts as a correctness fix and not a tuning change.",
            "Before it, the confidence score's denominator was arbitrary. Claims were marked "
            "unverified because of where they happened to sit in the draft relative to where "
            "their evidence happened to sit in the source list. The number moved for reasons that "
            "had nothing to do with the research.", "bad")),

    # ------------------------------------------------------------------ 6
    CH(6, "Verification and Confidence Scoring",
       "This chapter describes the part of the system that most distinguishes it, and the part "
       "where a plausible-looking implementation is most likely to be measuring something other "
       "than what it claims.",

       H3("6.1 Why naïve verification fails"),
       P("The obvious implementation extracts claims from the draft and checks them against the "
         "source documents. It is circular. A claim faithfully summarised from a source always "
         "agrees with that source, including when the source is wrong, and including when the "
         "claim is a hallucination the model then also used to write the summary."),
       P("Such a system measures summarisation fidelity while its interface calls the result "
         "grounding. It will report high confidence on a well-written answer built from three "
         "bad sources, which is precisely the case a reader most needs warning about."),

       H3("6.2 Independent corroboration"),
       P("Each extracted claim is searched for separately and concurrently. The results are "
         "labelled distinctly from the documents the draft was written from — [PRIOR] for "
         "evidence the analyst already saw, [INDEPENDENT] for evidence found by this search. A "
         "claim confirmed by a source the analyst never saw is marked "
         "independently_corroborated."),
       P("The verifier is instructed to cap its confidence at 0.7 when only prior evidence "
         "supports a claim. Agreement with one's own summary is weak evidence, and the prompt "
         "says so explicitly rather than leaving the model to infer it."),

       H3("6.3 Batching, and why it was necessary"),
       P("Verification originally ran one call per claim. On a representative run that consumed "
         "257 seconds of a 361-second total — the verification step was the product's latency. "
         "All claims now go in a single call, each paired with the evidence selected for it in "
         "§5.5."),
       P("A single-claim fallback remains for the case where the batch response fails to parse. "
         "It is slow and it is rarely reached, and it exists because returning no verification at "
         "all would silently produce a score of 0.0 that looks like a verdict rather than a "
         "parsing failure."),

       H3("6.4 Scoring the run"),
       P("The run's confidence is not the mean of its claim scores. A mean hides its worst "
         "member: four solid claims and one fabrication scored identically to five mediocre ones. "
         "Instead, unsupported claims are weighted more heavily, and the result is capped by the "
         "quality of the evidence beneath it — because thin evidence does not make an answer "
         "wrong, it makes a high score unjustifiable."),
       TBL(["Condition", "Effect", "Rationale"], [
           ["Unsupported claim present", "Weighted 1.5×", "Cannot be averaged away by its neighbours."],
           ["Fewer than 3 distinct sources", "Cap 60%", "Perfect claims over two documents is not a confident answer."],
           ["Fewer than 5 distinct sources", "Cap 80%", "Insufficient breadth for a high score."],
           ["Majority of sources snippet-only", "Cap 70%", "A search snippet is not the paper it stands for."],
           ["Independent corroboration", "Up to +10%", "Scaled by the proportion of claims confirmed externally."],
           ["No claims extracted", "Score 0.0", "An invented middling number reads as a measurement when nothing was measured."],
       ], [0.28, 0.16, 0.56]),
       P("The caps compose: a run can be limited by source count and by snippet ratio at once, "
         "and the lowest applicable cap wins. They are caps rather than penalties deliberately — "
         "a penalty is a subtraction that a few extra good claims can win back, and no number of "
         "good claims over two sources makes two sources into broad evidence."),

       H3("6.5 Reporting the score honestly"),
       P("Every adjustment is reported alongside the number, and the report carries a \"What "
         "limits this score\" section naming what would raise it — more sources, full text rather "
         "than snippets, independent corroboration of specific claims. A score a reader cannot "
         "interrogate is decoration."),
       P("Citations are validated in code before the report is assembled: every reference must "
         "resolve to a source the reader actually fetched. The sources list and the confidence "
         "block are joined in Python rather than generated by the model, which removes the last "
         "place in the pipeline where a reference could be invented.")),

    # ------------------------------------------------------------------ 7
    CH(7, "Data Layer and Security",
       "This layer is shared with Chat with Files, and is described here in full rather than "
       "cross-referenced, because a reader handed only this document should not have to go "
       "looking for it.",

       H3("7.1 Tenant isolation"),
       P("Application code filters every query by user. That is necessary and insufficient: it "
         "is one forgotten WHERE clause away from a cross-tenant leak. Postgres row-level "
         "security provides the second line. Policies are keyed on a session variable set when a "
         "connection is checked out of the pool, and current_setting(..., true) returns NULL "
         "when unset — so an unscoped session matches nothing and fails closed."),
       P("Two roles make this work. The owner role runs migrations and the payment webhook path, "
         "which has no user context and must read across tenants. The runtime role owns nothing "
         "and has no BYPASSRLS, so policies bind to it. If both connection strings name the same "
         "role, every policy is inert — and startup says so loudly rather than logging a "
         "reassuring line that means nothing."),
       TBL(["Check", "Expected", "Result"], [
           ["Owner reads their own rows", "Visible", "Pass"],
           ["Unfiltered SELECT by another tenant", "Zero rows", "Pass"],
           ["Session with no tenant set", "Zero rows (fail closed)", "Pass"],
           ["Insert a row under another tenant's id", "Refused by WITH CHECK", "Pass"],
       ], [0.46, 0.34, 0.20]),
       H4("Verified live · all six tables"),
       P("research_sessions, rag_documents, rag_conversations, rag_chunks, rag_messages and "
         "user_subscriptions all report relrowsecurity = true. These four checks run as a build "
         "gate; a regression fails CI rather than reaching production."),
       NOTE("A subtlety that cost a real bug.",
            "The session variable is bound to the connection, and a commit releases the "
            "connection back to the pool. Code that committed and then re-read the same row got a "
            "connection with the variable cleared, and row-level security correctly hid the row "
            "it had just written. The fix binds the tenant to a ContextVar so any connection "
            "checked out within the request is scoped the same way.", "bad"),

       H3("7.2 What this product persists"),
       P("A research run writes one row: the question, the finished Markdown report, the "
         "confidence score, the token count and the computed cost. Sources and per-claim verdicts "
         "travel inside that row's JSON payload rather than in tables of their own, because they "
         "are written once with the run and never queried across runs."),
       P("The token ledger is worth noting separately. Usage is accumulated in a ContextVar for "
         "the duration of a run and persisted with the session, which is what makes the cost "
         "figures in Chapter 9 measurements rather than estimates."),

       H3("7.3 Untrusted content on the research path"),
       P("This pipeline reads arbitrary web pages, which is to say it puts text written by "
         "strangers into a model's context. The defence is structural rather than lexical: "
         "fetched content is wrapped in delimiters and the system prompt states that anything "
         "inside them is data, never a command. A closing tag appearing inside the content is "
         "neutralised, or it would end the block early and hand back exactly the control the "
         "delimiter withholds."),
       P("A regex sanitiser also runs, and it is a speed bump rather than a defence. When this "
         "was tested with a realistic injection, the regex missed it entirely — its patterns "
         "expected different phrasing — and the structural delimiting held. The patterns were "
         "widened afterwards, but the lesson is that the delimiter is what works."),

       H3("7.4 Schema management"),
       P("Four Alembic revisions replace the earlier pattern of create_all() plus hand-written "
         "ADD COLUMN IF NOT EXISTS statements, which could add a column but never alter or remove "
         "one and recorded nothing about what had been applied. A database predating Alembic is "
         "stamped at the baseline rather than re-running it, so existing data is preserved.")),

    # ------------------------------------------------------------------ 8
    CH(8, "Testing and Continuous Integration",
       "The suite and the gates that protect this product, and the reason both are run against "
       "a real Postgres rather than a convenient substitute.",

       STATS(("74", "Tests for this product", "agents · confidence · evidence · graph"),
             ("38", "Shared platform tests", "auth and provider retry"),
             ("4", "Build gates", "tests · RLS · evals · frontend"),
             ("4", "Migrations", "versioned, reversible")),
       P("The 74 are the ones that fail when this pipeline breaks: test_agents.py, "
         "test_confidence.py, test_evidence.py and test_evals.py. Chat with Files has its own "
         "53 in test_rag.py, and they are not counted here — a number that covers both products "
         "tells you nothing about either."),

       H3("8.1 What CI verifies"),
       P("The pipeline runs against pgvector/pgvector:pg16 with a genuine low-privilege role — "
         "not SQLite. This matters: the application refuses to start on SQLite, so a suite "
         "running against it would cover none of the pgvector queries the corpus node makes, none "
         "of the tenant scoping, and none of the migrations that actually execute in production."),
       P("Beyond the unit suites, two gates assert behaviour rather than code. The first confirms "
         "Postgres genuinely refuses cross-tenant reads — the policies existing is not the same as "
         "the policies working. The second runs the golden evaluation set, so a retrieval "
         "regression fails the build."),

       H3("8.2 Tests that encode defects"),
       P("Several tests assert the specific failure rather than the happy path, so a regression "
         "reads as the thing that went wrong rather than as a number that moved:"),
       UL("an unsupported claim cannot be averaged away by four good ones "
          "(test_one_unsupported_claim_is_not_averaged_away);",
          "perfect claims over two sources are still capped "
          "(test_thin_evidence_caps_the_score);",
          "a corroborating hit on a page the draft already used is not counted as independent "
          "(test_sources_the_draft_already_used_are_not_counted_as_independent);",
          "a run with no claims scores 0.0, not an invented 0.5 "
          "(test_no_claims_scores_zero_not_a_default);",
          "a tracking parameter on a URL does not make a real citation look fabricated "
          "(test_tracking_params_do_not_cause_false_mismatches);",
          "the reflective loop stops at its ceiling rather than running on "
          "(test_gap_analysis_stops_at_max_iterations);",
          "corpus chunks are not crowded out by a flood of web sources "
          "(test_corpus_chunks_survive_a_flood_of_web_documents);",
          "triage fails open to deep when every classification path breaks "
          "(test_fails_open_to_deep_when_everything_breaks)."),
       NOTE("The workflow had never run.",
            "For most of this project's life the CI badge was green because no workflow had ever "
            "executed: the file sat one directory below the repository root, where GitHub Actions "
            "does not look. It was relocated and the first real run followed — which is how the "
            "SQLite problem above was found.", "bad")),

    # ------------------------------------------------------------------ 9
    CH(9, "Results and Measurements",
       "Every figure in this chapter was produced by running the system. Nothing here is an "
       "estimate, and where a measurement is weaker than it appears, this chapter says so.",

       H3("9.1 Internal golden set"),
       P("Run as a build gate on every push. Scores of 1.000 here mean \"no regression since the "
         "last commit\", and should not be read as evidence of accuracy — the questions were "
         "written by the author, over documents chosen by the author."),
       TBL(["Metric", "Score", "Baseline", "Result"], [
           ["Retrieval recall", "1.000", "1.000", "OK"],
           ["Answer accuracy", "1.000", "1.000", "OK"],
           ["Refusal rate", "1.000", "1.000", "OK"],
           ["Unanswerable retrieved something", "0.750", "1.000", "OK"],
       ], [0.46, 0.18, 0.18, 0.18]),

       H3("9.2 Confidence distribution across real runs"),
       P("Five genuine research runs against live web sources. The spread is the point: a system "
         "that returns a high score for every question is not measuring anything."),
       FIG("9.1", "Confidence by run, with token cost",
           "Confidence is not correlated with effort. The 18% run consumed more tokens than the "
           "65% run — it searched hard and still found little support, which is the honest "
           "outcome for a contested question.",
           "fig9-confidence.png", 700, 260),
       P("The 18% run is the most informative result in this report. Asked how much electricity "
         "data centres use worldwide, the system gathered 24 sources, supported one claim of "
         "five, corroborated none independently, and reported: \"4 claims had no supporting "
         "evidence in the sources found\" and \"agreement with the documents the answer was "
         "written from is weaker evidence.\" Data-centre energy figures are widely cited "
         "second-hand and poorly sourced. A system that returned 85% here would be worse, not "
         "better."),

       H3("9.3 Cost and latency"),
       STATS(("15,370", "Mean tokens / run", "across five live runs"),
             ("$0.0054", "Mean cost / run", "at published provider rates"),
             ("257 s → 1 call", "Verification", "before and after batching"),
             ("200,000", "Daily token ceiling", "free tier, provider-enforced")),
       P("The daily ceiling is the real constraint on this product, and it is invisible until it "
         "is hit — it appears only in the body of a 429 response, not in the published rate-limit "
         "table. At roughly 15,000 tokens per run it permits on the order of thirteen deep runs "
         "per day, which is why triage and batching are correctness features here rather than "
         "optimisations."),

       H3("9.4 Interface quality"),
       P("Measured in the browser against the running application, before and after the "
         "remediation work described in Chapter 10."),
       TBL(["Measure", "Before", "After", "Standard"], [
           ["Horizontal overflow at 375 px", "265 px", "0 px", "No sideways scroll"],
           ["Controls below 44 px touch target", "15 of 29", "0 of 29", "Apple HIG"],
           ["Visible keyboard focus", "None", "All controls", "WCAG 2.4.7"],
           ["Light-theme muted text contrast", "3.79 : 1", "4.72 : 1", "WCAG AA (4.5)"],
           ["Light-theme link contrast", "3.72 : 1", "4.84 : 1", "WCAG AA (4.5)"],
           ["Dark-theme colour pairs passing AA", "14 of 14", "14 of 14", "WCAG AA"],
           ["Frontend automated tests", "0", "31", "—"],
           ["Page height, signed-in home", "8,272 px", "2,740 px", "—"],
       ], [0.40, 0.18, 0.18, 0.24])),

    # ------------------------------------------------------------------ 10
    CH(10, "Evaluation, Limitations and Future Work",
       "What was found, what was fixed, and — more usefully — what is still not known about "
       "this product.",

       H3("10.1 Defects found and corrected"),
       P("A structured review of the codebase found a consistent pattern: several controls were "
         "documented in comments and marketing copy but did not exist in the running system. "
         "These are recorded because the pattern is more instructive than any individual bug."),
       TBL(["Defect", "Why it mattered", "Resolution"], [
           ["Row-level security absent", "Extensively documented as \"real defense-in-depth\"; zero policies existed and both connection strings named the same role.", "Policies written, second role created, four checks gated in CI."],
           ["Circular verification", "Claims checked against the text they were summarised from; the score measured fidelity, not support.", "Independent per-claim search and a corroboration flag."],
           ["Evidence truncation", "Verification saw roughly six of forty sources, making most claims unverifiable in principle.", "Relevance-based selection across all sources."],
           ["Confidence by mean", "One fabrication among four good claims scored the same as five mediocre ones.", "Weighted aggregate with evidence-quality caps."],
           ["Verification latency", "257 s of a 361 s run spent on per-claim calls.", "Batched into one call with per-claim evidence."],
           ["CI ran on SQLite", "The application refuses to start on SQLite; the green check covered none of the production data paths.", "Postgres + pgvector service container."],
           ["CI had never executed", "The workflow file sat one directory below the repository root, where GitHub Actions does not look.", "Relocated; first successful run followed."],
           ["Quota double-spend", "The counter was re-read after commit, silently consuming several queries per run.", "Read once, within the scoped session."],
       ], [0.20, 0.44, 0.36]),

       H3("10.2 Current limitations"),
       UL("Quota refunding is implemented and uncovered. refund_quota() is called on the "
          "failure path in api/main.py, and no test asserts that it runs — so a regression "
          "there would charge a user for a run that failed, silently.",
          "The confidence score is unvalidated against human judgement. A harness exists to "
          "measure whether \"verified\" correlates with \"true\", but it requires human labels "
          "that have not yet been collected. This is the single largest gap in this product's "
          "evidence, and nothing else on this list comes close.",
          "Five runs is a small sample. The spread is encouraging but it is not a distribution.",
          "The pipeline runs in the web process. A restart mid-run loses the run; the quota is "
          "refunded but the work is not recoverable.",
          "Reader success rate is unmeasured. The proportion of sources that degrade to snippets "
          "is recorded per run and reported, but never aggregated across runs.",
          "Triage accuracy is unmeasured. It fails open, so errors are expensive rather than "
          "wrong — but that is an argument for measuring it, not for assuming it."),

       H3("10.3 Future work, in priority order"),
       UL("Collect human labels for 100 or more verified claims and report precision, recall and "
          "calibration of the confidence score. Nothing else changes this product's credibility "
          "as much.",
          "Aggregate reader success and snippet ratios across runs, so the caps in §6.4 can be "
          "justified with a distribution rather than an argument.",
          "Move the pipeline behind a durable queue so a restart does not lose a run.",
          "Measure triage accuracy against a labelled set of messages.",
          "Cache fetched pages across runs; the same sources recur and re-fetching them spends "
          "latency on nothing."),

       H3("10.4 Assessment"),
       P("This product does what it claims within the limits of what has been measured. Its "
         "verification is genuinely independent rather than circular. Its confidence scoring is "
         "conservative by construction and reports its own reasoning. Its security controls are "
         "enforced by the database and verified by the build, rather than described in a comment."),
       P("What remains unproven is whether the confidence number corresponds to truth. Every "
         "measurement in Chapter 9 captures internal consistency or retrieval behaviour. None "
         "answers the question a reader actually has — when it says 77%, is that right? — and "
         "until human labels exist, that question is open. This report states that plainly "
         "rather than letting a column of 1.000 scores imply otherwise.")),
]
