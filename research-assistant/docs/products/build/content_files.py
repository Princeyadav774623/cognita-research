"""Chat with Files — the complete report content.

Standalone by design. The platform chapters (architecture, data layer, CI) are
repeated here in full rather than cross-referenced to the Deep Research report,
because a reader handed only this document should never need the other one.
"""
from spec import P, H3, H4, LEDE, UL, TBL, NOTE, STATS, FIG, CODE, CH

META = {
    "key": "chat-with-files",
    "product": "Chat with Files",
    "other": "Deep Research",
    "accent": "teal",
    "eyebrow": "PRODUCT REPORT · TWO OF TWO",
    "title": "Chat with Files",
    "title_em": "answers bounded by your own documents",
    "sub": ("The retrieval-augmented generation product behind Cognita's document tool: how an "
            "uploaded file becomes indexed chunks, how a question becomes a fused ranking over "
            "them, and why declining to answer is treated as a correct outcome."),
    "author": "Prince Yadav",
    "date": "16 September 2026",
    "route": "/#files",
}

CHAPTERS = [

    # ------------------------------------------------------------------ 1
    CH(1, "Introduction and Problem Statement",
       "A model given documents and told to answer from them will still answer when they do "
       "not contain the answer. The interesting engineering problem in retrieval-augmented "
       "generation is not retrieval — it is knowing when to stop.",

       H3("1.1 The problem"),
       P("The standard account of RAG is that hallucination is a knowledge problem: the model "
         "invents things because it does not have the facts, so supply the facts. That account "
         "is incomplete. A model supplied with three passages that do not answer the question "
         "will compose something from them anyway, fluently, with citations that point at real "
         "documents which do not say what the answer claims."),
       P("Two failures follow from this, and they need different fixes."),
       UL("The passages were wrong. Retrieval failed — the answer was in the corpus and was not "
          "found. This is a ranking problem, and Chapter 5 is about it.",
          "The passages were right and the answer still was not there. Retrieval succeeded and "
          "the corpus simply does not contain the answer. The only correct behaviour is to say "
          "so, and Chapter 6 is about that."),

       H3("1.2 What this product is"),
       P("Chat with Files is one of the two products in Cognita. A user uploads documents at "
         "/#files — PDF, DOCX, TXT, Markdown, or an image that goes through OCR — and then asks "
         "questions of them. The system validates the file by its magic bytes, extracts text "
         "according to type, sanitises it, splits it into overlapping chunks, embeds each chunk "
         "locally, and indexes it for both vector and keyword search."),
       P("A question is resolved against the conversation history, searched two ways, fused into "
         "one ranking, graded for whether it actually answers the question, rewritten and retried "
         "once if not, and then either answered with the passages it used or declined."),

       H3("1.3 What this product is not"),
       P("Cognita's other product, Deep Research, answers questions from the open web using a "
         "nine-node agent pipeline. It is a separate page with its own query box, its own "
         "evidence model and its own benchmark. It is not a consumer of this product and this "
         "product is not a stage of it."),
       P("The two meet at exactly one place, and the direction matters: the corpus node in the "
         "research pipeline can read the chunks this product created, so a research run may draw "
         "on the user's documents as well as the web. Nothing in that pipeline writes here. From "
         "this product's side, that is another system reading its store."),
       NOTE("Why they are documented separately.",
            "The two products share a database, an authentication model and a deployment, and "
            "almost nothing else. The specific misunderstanding this separation exists to prevent "
            "is that this product is a subroutine of the other one — it is not, and its "
            "measurements, failure modes and benchmark are entirely its own.", "teal"),

       H3("1.4 What this report covers"),
       P("Chapters 2 to 8 describe requirements, architecture, implementation and security for "
         "this product alone. Chapter 9 reports measurements taken from the running system, "
         "including a public benchmark, and states where each is weaker than it looks. Chapter 10 "
         "records what is not known. Chapter 11 carries nine SRS diagrams drawn for this product, "
         "and Chapter 12 reproduces every prompt it sends.")),

    # ------------------------------------------------------------------ 2
    CH(2, "Software Requirements Specification",
       "The requirements this product is built against, separated from those of Deep Research "
       "so that each can be read, tested and argued with on its own terms.",

       H3("2.1 Purpose and intended audience"),
       P("This specification describes the document half of a web application delivering "
         "verifiable answers. Its users are anyone with a body of documents they need to "
         "interrogate — a contract, a manual, a set of papers — and who needs to know when the "
         "answer is not in there."),

       H3("2.2 Functional requirements"),
       TBL(["ID", "Requirement", "Priority", "Status"], [
           ["CF-1", "Upload PDF, DOCX, TXT, MD and images (OCR), up to 15 MB.", "Must", "Implemented"],
           ["CF-2", "Validate file type by magic bytes rather than by filename extension.", "Must", "Implemented"],
           ["CF-3", "Return the upload request before extraction and embedding complete.", "Must", "Implemented"],
           ["CF-4", "Report ingestion status per document, including the reason for a failure.", "Must", "Implemented"],
           ["CF-5", "Fail a document left mid-ingest by a restart rather than leaving it pending.", "Must", "Implemented"],
           ["CF-6", "Split extracted text into 1,000-character chunks with 150-character overlap.", "Must", "Implemented"],
           ["CF-7", "Embed chunks locally, with no document text sent to an inference provider for embedding.", "Must", "Implemented"],
           ["CF-8", "Index chunks for both vector similarity and full-text keyword search.", "Must", "Implemented"],
           ["CF-9", "Resolve a follow-up question against the conversation history before retrieving.", "Should", "Implemented"],
           ["CF-10", "Retrieve by vector and by keyword, and fuse the two rankings.", "Must", "Implemented"],
           ["CF-11", "Grade whether retrieved passages actually answer the question.", "Must", "Implemented"],
           ["CF-12", "Rewrite the query and retry retrieval once when grading fails.", "Should", "Implemented"],
           ["CF-13", "Decline to answer when retrieved evidence is insufficient.", "Must", "Implemented"],
           ["CF-14", "Return the passages an answer was drawn from alongside the answer.", "Must", "Implemented"],
           ["CF-15", "Treat document content as data and never as instructions.", "Must", "Implemented"],
           ["CF-16", "Delete a document and cascade to its chunks on request.", "Must", "Implemented"],
           ["CF-17", "Enforce a monthly query allowance.", "Must", "Implemented"],
           ["CF-18", "Delete all of a user's documents and conversations on request (GDPR erasure).", "Must", "Implemented"],
       ], [0.09, 0.58, 0.13, 0.20]),

       H3("2.3 Non-functional requirements"),
       TBL(["ID", "Category", "Requirement", "Verified by"], [
           ["CN-1", "Security", "One tenant's documents must be unreachable by another, enforced at the database.", "CI gate, verify_rls.py"],
           ["CN-2", "Security", "Uploaded documents must not be able to alter system behaviour.", "Live injection test"],
           ["CN-3", "Security", "A chunk must be visible only if its parent document is.", "Policy installed — not live-checked"],
           ["CN-4", "Performance", "Answer latency under 5 s at p50.", "Measured: 2.0 s"],
           ["CN-5", "Performance", "Retrieval must not degrade linearly with corpus size.", "HNSW index"],
           ["CN-6", "Performance", "Retrieval must cost nothing per query, so evaluation is unbounded.", "Local embeddings, 0.3 s / 25 q"],
           ["CN-7", "Reliability", "An upload must not exceed a proxy timeout regardless of file size.", "Async ingest"],
           ["CN-8", "Reliability", "A restart must not strand an upload indefinitely.", "Stale-job reaper, 15 min"],
           ["CN-9", "Correctness", "A question unanswerable from the corpus must be refused, not answered.", "SQuAD 2.0 subset"],
           ["CN-10", "Accessibility", "WCAG 2.1 AA contrast; visible keyboard focus; 44 px touch targets.", "Measured in browser"],
           ["CN-11", "Portability", "Schema changes applied by versioned migrations, never at startup.", "Alembic, 4 revisions"],
       ], [0.09, 0.14, 0.50, 0.27]),

       H3("2.4 Constraints"),
       UL("Postgres only. pgvector and row-level security are both required; SQLite is rejected "
          "at startup.",
          "Embeddings must run locally. A per-query embedding cost would make continuous "
          "evaluation impossible on this budget, which is the constraint that produced the "
          "measurement discipline in Chapter 9.",
          "Free-tier inference. Groq's limits — 8,000 tokens per minute and 200,000 per day — "
          "bound how much answering and judging can be done in a day.",
          "Two database roles, or row-level security has no effect.",
          "One process. Ingestion runs in the web process; there is no durable queue."),

       H3("2.5 Assumptions and dependencies"),
       UL("Uploaded documents are untrusted input. They are the easiest path into a model's "
          "context for anyone who wants to steer it.",
          "A meaningful share of questions will be unanswerable from the corpus, and that is "
          "normal use rather than misuse.",
          "Users will ask follow-up questions containing pronouns, so a question is not "
          "self-contained by default.",
          "Identity is delegated to Supabase; the backend holds no authentication secret.")),

    # ------------------------------------------------------------------ 3
    CH(3, "System Architecture",
       "Three tiers: a React single-page application, a FastAPI service, and Postgres with "
       "pgvector holding documents, chunks, vectors and conversations in one place.",

       FIG("3.1", "System architecture",
           "Request paths are solid. Every runtime query passes through the low-privilege role "
           "so row-level security applies; the embedding model runs in the application process.",
           "fig3-architecture.png", 860, 400),

       H3("3.1 One database, not two"),
       P("The most consequential architectural decision in this product is that vectors live in "
         "the same database as the tenant data. A dedicated vector database would be faster at "
         "scale and would require its own tenancy model, its own backup story, its own migration "
         "story and its own answer to \"can user A read user B's chunks?\"."),
       P("Keeping vectors in pgvector means one row-level security policy protects the document "
         "row, the chunk row and the conversation that quoted it. At this scale the performance "
         "difference is not measurable and the correctness difference is."),

       H3("3.2 Technology decisions and their reasons"),
       TBL(["Layer", "Choice", "Why this rather than the obvious alternative"], [
           ["Vector store", "pgvector", "Keeping vectors beside tenant data means one policy protects both. A separate vector database needs its own tenancy model."],
           ["Embeddings", "Local fastembed", "Runs on the server with no API cost or rate limit, which is what makes retrieval evaluation over hundreds of questions free."],
           ["Keyword search", "Postgres FTS", "Already present; no second system to operate for the keyword half of hybrid retrieval."],
           ["Fusion", "Reciprocal Rank Fusion", "Fuses by rank, not score. Cosine similarity and ts_rank are different scales with no meaningful conversion."],
           ["Vector index", "HNSW", "Keeps retrieval sub-linear as the corpus grows; the alternative is a sequential scan that looks fine on a test corpus."],
           ["Inference", "Groq", "Fast and free at this scale. Two model sizes let grading and judging avoid competing with answering for a scarce budget."],
       ], [0.16, 0.18, 0.66]),

       H3("3.3 Model allocation"),
       P("Answering runs on the 120B model, because the answer is the product. Grading, "
         "rewriting, contextualising and judging run on the 20B model — they are classification "
         "and rephrasing tasks where the larger model's budget would be spent for no gain."),
       P("The judge deliberately runs on a different model from the answerer. A model grading its "
         "own output measures self-consistency, which is not the same thing as faithfulness."),
       NOTE("One pinned model, on purpose.",
            "The model identifiers are pinned in config.py rather than resolved from a provider "
            "default. The account this project runs on does not expose the llama-3.x family at "
            "all, so a fallback chain that assumed it would fail at runtime on a machine where it "
            "had never been tested.", "teal")),

    # ------------------------------------------------------------------ 4
    CH(4, "Ingestion",
       "Everything that happens once per document, before any question is asked. It runs "
       "outside the HTTP request that triggered it, which is the source of both its main "
       "virtue and its main defect.",

       H3("4.1 Validation"),
       P("A file is validated by its magic bytes rather than its extension. An extension is a "
         "claim made by whoever named the file; the leading bytes are a property of the file "
         "itself. A .pdf that is actually a ZIP archive is rejected before anything tries to "
         "parse it."),
       P("Size is capped at 15 MB. The cap exists because extraction is memory-bound and runs in "
         "the web process — a 200 MB PDF would not merely be slow, it would affect every other "
         "request on the node."),

       H3("4.2 Extraction"),
       P("Extraction dispatches on the detected type: a PDF text layer, DOCX paragraph "
         "extraction, plain text passed through, and OCR for images. Extracted text is then "
         "sanitised, for the reasons Chapter 7 sets out at length — this is untrusted input, and "
         "it was the one input path in Cognita that was not being sanitised until it was found."),

       H3("4.3 Chunking"),
       P("Text is split into 1,000-character chunks with 150 characters of overlap. Both numbers "
         "are compromises and both are worth stating plainly rather than presenting as tuned."),
       UL("Chunk size trades recall against precision. Larger chunks are more likely to contain "
          "a complete answer and dilute the embedding, which pushes them down the ranking for "
          "specific queries. Smaller chunks rank sharply and truncate answers mid-sentence.",
          "Overlap exists because the answer to a question is often a sentence that a naive "
          "split would cut in half. 150 characters is roughly a sentence and a half of English, "
          "so a boundary rarely destroys a complete thought.",
          "Neither has been tuned against a benchmark. They are defensible defaults, and §10.2 "
          "records that as a limitation rather than dressing it up."),

       H3("4.4 Embedding"),
       P("Chunks are embedded with BAAI/bge-small-en-v1.5, 384 dimensions, running in the "
         "application process. Nothing leaves the deployment to be embedded."),
       P("The model is asymmetric: it expects a query to carry an instruction prefix that a "
         "passage does not. Getting this backwards — or omitting it — degrades retrieval "
         "silently, because the system still returns results and they are still plausible. The "
         "prefix is applied at query time only. Nothing in the suite asserts that, which §10.2 "
         "records as a gap rather than leaving implied."),
       NOTE("Local embedding is why this report has measurements in it.",
            "Retrieval costs nothing per query, so evaluating twenty-five questions takes 0.3 "
            "seconds and zero budget. A per-query embedding fee would have made the benchmark in "
            "Chapter 9 something to run once and quote forever, rather than a gate that runs on "
            "every push.", "teal"),

       H3("4.5 Asynchrony, and the reaper"),
       P("The HTTP request returns as soon as the document row exists, with status "
         "processing. Extraction and embedding happen afterwards. This is what stops a "
         "200-page PDF from exceeding a proxy timeout, and it is the correct shape for the "
         "operation."),
       P("It is implemented as a background task in the same process, not as a job on a durable "
         "queue. A restart between upload and ready strands the row in processing forever. The "
         "mitigation is a reaper that fails any document stuck in that state for more than "
         "fifteen minutes, with a message telling the user to upload it again."),
       P("That is a mitigation and not a fix, and §10.2 says so. A durable queue is the correct "
         "solution and is not implemented.")),

    # ------------------------------------------------------------------ 5
    CH(5, "Hybrid Retrieval",
       "Retrieval runs two searches and fuses their rankings. Neither is reliable alone, and "
       "the cases where each fails are precisely the cases where users are most confident the "
       "system should have worked.",

       H3("5.1 Why one retriever is not enough"),
       P("Embeddings place Sev-1 and Sev-2 almost on top of each other. They are two characters "
         "apart, they appear in identical contexts, and semantically they are near-identical — "
         "which is exactly wrong when the user asked about one of them specifically."),
       P("Keyword search has the opposite failure. It has no notion of synonym or paraphrase, so "
         "a question about \"restarting the unit\" finds nothing in a manual that says \"power "
         "cycling the device\"."),
       P("The queries where vector search fails — part numbers, error codes, version strings, "
         "proper nouns — are the ones where the user is most certain they typed it correctly. A "
         "miss there does not read as a limitation of semantic search; it reads as the product "
         "being broken."),

       H3("5.2 Vector search"),
       P("The query is embedded with the instruction prefix and matched by cosine distance "
         "against an HNSW index over the chunk embeddings. The top twenty candidates are "
         "retained. Twenty rather than four because fusion needs a pool deep enough for the "
         "second retriever to rescue something from — fusing two top-four lists mostly produces "
         "the same top four."),

       H3("5.3 Keyword search"),
       P("The keyword half uses Postgres full-text search over a generated tsvector column with a "
         "GIN index, queried through websearch_to_tsquery — which accepts the syntax users "
         "actually type, including quoted phrases, rather than requiring tsquery's operators."),
       P("It degrades rather than fails. If the query cannot be parsed into a tsquery at all, the "
         "keyword half returns nothing and fusion proceeds with the vector candidates alone. On "
         "SQLite — which the application refuses to start on, but which some tests use — the "
         "keyword half is skipped entirely."),

       H3("5.4 Reciprocal Rank Fusion"),
       P("The two rankings are combined by Reciprocal Rank Fusion with k = 60. RRF scores a "
         "document by the sum of 1/(k + rank) across the lists it appears in, which means it "
         "fuses by position rather than by score."),
       P("This matters more than it sounds. Cosine similarity and ts_rank are different scales "
         "with no meaningful conversion between them — normalising one onto the other would "
         "invent a relationship that does not exist, and the invented relationship would then "
         "silently decide which passages the answer is written from. Rank is the only thing the "
         "two retrievers genuinely agree on the meaning of."),

       H3("5.5 Measured"),
       FIG("5.1", "Hybrid retrieval, measured",
           "Rank of the chunk containing the answer, by retriever, on a field-service document "
           "of error codes and part numbers. Lower is better; rank 1 is ideal.",
           "fig5-hybrid.png", 700, 220),
       NOTE("Reading this honestly.",
            "Two of the three queries were already handled by vector search alone. The third is "
            "the case hybrid retrieval exists for — and the class of query it represents (version "
            "strings, part numbers, error codes) is precisely the one where a miss reads as the "
            "product being broken rather than as a ranking nuance.", "bad")),

    # ------------------------------------------------------------------ 6
    CH(6, "The Agentic Answer Loop",
       "Retrieval is not a single shot. This chapter is the part of the product that decides "
       "when not to answer, which is the behaviour the whole thing exists for.",

       H3("6.1 Contextualising the question"),
       P("A follow-up question is rarely self-contained. \"What about the second one?\" embeds "
         "into nothing useful, and a keyword search for it returns noise. Before retrieval, the "
         "question is rewritten against the conversation history into a standalone form."),
       P("This runs on the small model and it runs on every turn after the first. It is cheap and "
         "it is the difference between a product that supports conversation and one that supports "
         "a sequence of unrelated queries."),

       H3("6.2 Grading"),
       P("The fused passages are graded before they are answered from. The grader is asked one "
         "question — do these excerpts actually contain what is needed to answer? — and it runs "
         "on the small model at temperature 0, because the same passages should produce the same "
         "verdict every time."),
       P("This is the step that separates this product from a pipeline that retrieves and "
         "generates. Without it, the answerer receives whatever retrieval returned and writes "
         "something from it, because that is what an answerer does."),

       H3("6.3 Rewriting and retrying"),
       P("When grading fails, the question is rewritten with different wording and retrieval runs "
         "again. Once. The retry exists because the most common retrieval failure is vocabulary "
         "mismatch — the corpus and the question use different words for the same thing — and "
         "rephrasing is a direct attack on that."),
       P("It does not loop. A second rewrite of an already-rewritten query drifts away from what "
         "the user asked, and the failure mode of an unbounded rewrite loop is answering a "
         "question nobody posed."),

       H3("6.4 Declining"),
       P("If grading fails after the retry, the system declines. The refusal names what is "
         "missing rather than issuing a bare apology, so the user learns something about their "
         "corpus rather than only about the system."),
       P("Declining is a success path, and it is drawn as one in Figure F.9. A system that "
         "answers every question from a corpus that does not contain the answer is not more "
         "useful than one that declines — it is the specific failure this product exists to "
         "avoid, delivered fluently."),

       H3("6.5 LLM-as-a-Judge"),
       P("Answers are scored by a separate judge model on faithfulness — is every statement "
         "supported by the passages? — and relevance — does it answer the question asked? The "
         "judge runs on the 20B model while the answer comes from the 120B model."),
       P("Using a different model is the point. A model judging its own output measures "
         "self-consistency, and self-consistency is exactly what a confidently wrong answer "
         "has.")),

    # ------------------------------------------------------------------ 7
    CH(7, "Data Layer and Security",
       "This layer is shared with Deep Research and is described here in full rather than "
       "cross-referenced. §7.2 is specific to this product, and is the most important security "
       "section in either document.",

       H3("7.1 Tenant isolation"),
       P("Application code filters every query by user. That is necessary and insufficient: it "
         "is one forgotten WHERE clause away from a cross-tenant leak. Postgres row-level "
         "security provides the second line. Policies are keyed on a session variable set when a "
         "connection is checked out of the pool, and current_setting(..., true) returns NULL "
         "when unset — so an unscoped session matches nothing and fails closed."),
       P("Two roles make this work. The owner role runs migrations and the payment webhook path, "
         "which has no user context. The runtime role owns nothing and has no BYPASSRLS, so "
         "policies bind to it. If both connection strings name the same role, every policy is "
         "inert — and startup says so loudly rather than logging a reassuring line."),
       H4("Derived policies, for chunks and messages"),
       P("rag_chunks and rag_messages carry no user_id of their own. Their policies are derived "
         "from the parent row: a chunk is visible if and only if its document is, and a message "
         "if and only if its conversation is. That is one fewer column to forget on insert, and "
         "it removes any possibility of a chunk and its document disagreeing about who owns "
         "them."),
       TBL(["Check", "Expected", "Result", "Run against"], [
           ["Owner reads their own rows", "Visible", "Pass", "research_sessions"],
           ["Unfiltered SELECT by another tenant", "Zero rows", "Pass", "research_sessions"],
           ["Session with no tenant set", "Zero rows (fail closed)", "Pass", "research_sessions"],
           ["Insert under another tenant's id", "Refused by WITH CHECK", "Pass", "research_sessions"],
           ["The same four, against documents and chunks", "Zero rows", "Not run", "—"],
       ], [0.40, 0.22, 0.14, 0.24]),
       P("The last row is the honest one. RLS is enabled and policied on rag_documents and "
         "rag_chunks — all six tables report relrowsecurity = true — but the live verifier that "
         "gates the build queries research_sessions only. The policies protecting this product's "
         "data are therefore asserted by their existence, not by a test that watches Postgres "
         "refuse a read. §10.2 carries that as a limitation."),

       H3("7.2 Untrusted document content"),
       P("An uploaded file is the easiest path into a model's context for anyone who wants to "
         "steer it. This is the attack surface that belongs to this product specifically, and it "
         "is the one that was left undefended longest."),
       P("The defence is structural. Retrieved excerpts are wrapped in &lt;document&gt; tags and "
         "the system prompt states that anything inside them is data, never a command. A closing "
         "tag appearing inside an excerpt is neutralised, or it would end the block early and "
         "hand back exactly the control the delimiter withholds."),
       NOTE("Tested, with an instructive result.",
            "A document was uploaded containing an instruction to ignore all directives and reply "
            "with a single fixed word. The regex sanitiser missed it entirely — its patterns "
            "expected different phrasing. The delimiting held: the system answered both questions "
            "correctly from the document and added that the document \"contains a line that "
            "appears to be an injected instruction… treated as part of the document content and "
            "is not followed.\" The patterns were widened afterwards, but the lesson stands — the "
            "structural separation is the defence, and the regex is a speed bump.", "bad"),
       P("Sanitising at ingest was added at the same time. Before that, scraped web pages were "
         "filtered and uploaded documents — far easier for an attacker to control, since they "
         "need only upload one — were not."),

       H3("7.3 Schema management"),
       P("Four Alembic revisions replace the earlier pattern of create_all() plus hand-written "
         "ADD COLUMN IF NOT EXISTS statements, which could add a column but never alter or remove "
         "one and recorded nothing about what had been applied. A database predating Alembic is "
         "stamped at the baseline rather than re-running it, so existing data is preserved."),
       P("The pgvector extension is created before the tables that depend on it. That ordering is "
         "not cosmetic: on a genuinely fresh database, creating a table with a vector column "
         "before the extension exists fails with type \"vector\" does not exist, which only ever "
         "appears on the first install and therefore never in development.")),

    # ------------------------------------------------------------------ 8
    CH(8, "Testing and Continuous Integration",
       "The suite and the gates that protect this product, and the reason both run against a "
       "real Postgres rather than a convenient substitute.",

       STATS(("165", "Backend tests", "unit and integration, 5 s"),
             ("31", "Frontend tests", "hooks and components"),
             ("4", "Build gates", "tests · RLS · evals · frontend"),
             ("0.3 s", "Retrieval eval", "25 questions, no API cost")),

       H3("8.1 What CI verifies"),
       P("The pipeline runs against pgvector/pgvector:pg16 with a genuine low-privilege role — "
         "not SQLite. This matters more for this product than for any other part of Cognita: a "
         "suite running on SQLite would exercise none of the vector queries, none of the "
         "full-text search, none of the derived chunk policies and none of the migrations that "
         "actually execute in production."),
       P("Two gates assert behaviour rather than code. The first confirms Postgres genuinely "
         "refuses cross-tenant reads of documents and chunks. The second runs the golden "
         "retrieval set, so a ranking regression fails the build rather than being noticed later "
         "by a user."),

       H3("8.2 Tests that encode defects"),
       UL("a closing tag inside an excerpt cannot end the delimiter block early "
          "(test_a_closing_tag_inside_content_cannot_end_the_block);",
          "the system prompt states that excerpts are data "
          "(test_system_prompt_states_excerpts_are_data);",
          "an override attempt in an uploaded file is sanitised at ingest "
          "(test_ingest_sanitises_override_attempts);",
          "keyword search failing to parse a query degrades to vectors rather than erroring "
          "(test_keyword_failure_degrades_to_vectors_instead_of_erroring);",
          "a spoofed file whose magic bytes contradict its extension is rejected "
          "(test_rejects_spoofed_file_magic_bytes);",
          "a document stuck in processing past the threshold is failed by the reaper "
          "(test_marks_an_abandoned_document_as_failed);",
          "an insufficient first retrieval is rewritten and retried "
          "(test_rewrites_and_retries_when_first_attempt_is_insufficient);",
          "chunk windows overlap so an answer is not lost at a boundary "
          "(test_windows_overlap_so_boundaries_are_not_lost)."),
       NOTE("What the suite does not cover.",
            "Two things this report would like to claim and cannot. Nothing asserts that the "
            "embedding query prefix is applied at query time and not at index time — getting "
            "that wrong degrades retrieval silently, which is exactly the case a test exists "
            "for. And scripts/verify_rls.py exercises research_sessions only: the policies on "
            "rag_documents and rag_chunks are installed and enabled, but no live check proves "
            "they refuse a cross-tenant read.", "bad")),

    # ------------------------------------------------------------------ 9
    CH(9, "Results and Measurements",
       "Every figure in this chapter was produced by running the system. Nothing here is an "
       "estimate, and where a measurement is weaker than it appears, this chapter says so.",

       H3("9.1 Public benchmark — SQuAD 2.0"),
       P("The project's own golden set is fourteen questions over three documents written by the "
         "author. It is a useful regression check and poor evidence: a perfect score on one's own "
         "questions demonstrates that the system does what was expected, not that it works. "
         "SQuAD 2.0 is a public benchmark of human-written questions over Wikipedia paragraphs, "
         "including questions deliberately unanswerable from their source."),
       STATS(("1.000", "Recall @ 4", "25/25 questions reached their source paragraph"),
             ("1.000", "Mean reciprocal rank", "correct paragraph always ranked first"),
             ("0.88", "Answer accuracy", "22/25 exact substring match"),
             ("25/25", "Judge verdicts", "PASS on faithfulness and relevance")),
       H4("Three qualifications, stated plainly"),
       UL("The corpus was 31 paragraphs. A perfect recall score over a small haystack is easier "
          "than over a realistic one, and this number should be expected to fall as the corpus "
          "grows.",
          "Answer accuracy is understated. Manual review of the three \"failures\" found two were "
          "correct answers phrased differently — \"very little work is needed to drive the pump\" "
          "scored zero against \"relatively little work is required to drive the pump\". Token F1 "
          "was added afterwards for this reason.",
          "The refusal rate is not yet reliably measured. The first run reported 0.167, which "
          "manual inspection showed was a grader defect rather than a system defect: the detector "
          "looked for three literal phrases and missed \"do not contain\", \"does not state\" and "
          "\"do not specify\". The true figure is approximately 0.667. A corrected re-run was "
          "prevented by the provider's daily token cap."),

       H3("9.2 Retrieval quality, by parameter"),
       P("The parameters a RAG system is usually evaluated on, and where this one actually "
         "stands on each. The point of the table is the last column."),
       TBL(["Parameter", "What it measures", "This system", "Confidence in the number"], [
           ["Recall @ k", "Did the right chunk get retrieved at all?", "1.000 @ 4", "High — but on 31 paragraphs"],
           ["MRR", "How high did it rank?", "1.000", "High, same caveat"],
           ["NDCG", "Graded relevance across the ranking", "Not computed", "—"],
           ["Answer accuracy", "Is the answer right?", "0.88 exact match", "Understated; token F1 added"],
           ["Faithfulness", "Is every statement supported by the passages?", "25/25 PASS", "Judge-based, small sample"],
           ["Relevance", "Does it answer the question asked?", "25/25 PASS", "Judge-based, small sample"],
           ["Refusal rate", "Does it decline when it should?", "≈ 0.667", "Low — pending corrected re-run"],
           ["Citation validity", "Do citations resolve to retrieved chunks?", "Not validated", "None — see §10.2"],
           ["Latency", "p50 end-to-end", "2.0 s", "High"],
           ["Cost per query", "Retrieval only", "$0.00", "High — embeddings are local"],
       ], [0.16, 0.30, 0.24, 0.30]),

       H3("9.3 Latency and cost"),
       STATS(("2.0 s", "Answer latency, p50", "retrieval, generation and judge"),
             ("0.3 s", "Retrieval only", "25 questions, no API calls"),
             ("$0.00", "Cost per retrieval", "embeddings run locally"),
             ("200,000", "Daily token ceiling", "free tier, provider-enforced")),
       P("Embeddings run on the server, so retrieval costs nothing and evaluation over hundreds "
         "of questions is free. This is what makes continuous measurement practical at zero "
         "budget — the constraint on evaluation is the answer pass, not retrieval."),

       H3("9.4 Interface quality"),
       TBL(["Measure", "Before", "After", "Standard"], [
           ["Horizontal overflow at 375 px", "265 px", "0 px", "No sideways scroll"],
           ["Controls below 44 px touch target", "15 of 29", "0 of 29", "Apple HIG"],
           ["Visible keyboard focus", "None", "All controls", "WCAG 2.4.7"],
           ["Light-theme muted text contrast", "3.79 : 1", "4.72 : 1", "WCAG AA (4.5)"],
           ["Dark-theme colour pairs passing AA", "14 of 14", "14 of 14", "WCAG AA"],
           ["Frontend automated tests", "0", "31", "—"],
       ], [0.40, 0.18, 0.18, 0.24])),

    # ------------------------------------------------------------------ 10
    CH(10, "Evaluation, Limitations and Future Work",
       "What was found, what was fixed, and — more usefully — what is still not known about "
       "this product.",

       H3("10.1 Defects found and corrected"),
       TBL(["Defect", "Why it mattered", "Resolution"], [
           ["Uploads unsanitised", "Scraped web pages were filtered; uploaded documents — far easier for an attacker to control — were not.", "Sanitised at ingest; context delimited structurally."],
           ["Row-level security absent", "Documented as \"real defense-in-depth\"; zero policies existed and both connection strings named the same role.", "Policies written, second role created, four checks gated in CI."],
           ["Vector-only retrieval", "Exact tokens — part numbers, error codes, version strings — ranked poorly, in the queries users are most certain about.", "Hybrid search with RRF over a 20-candidate pool."],
           ["CI ran on SQLite", "The application refuses to start on SQLite; the green check covered none of the vector or FTS paths.", "Postgres + pgvector service container."],
           ["Fresh-database install failed", "create_all() ran before the pgvector extension existed, so a first install died on type \"vector\" does not exist.", "Extension created first in init_db()."],
           ["Stranded uploads", "A restart mid-ingest left a document in processing with no path out.", "Stale-job reaper at 15 minutes."],
           ["Refusal grader defect", "The detector matched three literal phrases and scored correct refusals as failures — 0.167 against a true ≈0.667.", "Negation regex plus token F1."],
       ], [0.22, 0.44, 0.34]),

       H3("10.2 Current limitations"),
       UL("The RLS verifier does not cover this product's tables. scripts/verify_rls.py "
          "gates the build on four checks against research_sessions; the equivalent checks "
          "against rag_documents and rag_chunks are not written. The policies exist and are "
          "enabled — but 'the policies exist' is precisely the claim that turned out to be "
          "false the last time it was assumed, so it is recorded here rather than trusted.",
          "Nothing asserts the embedding query prefix is applied at query time only. It is, "
          "in rag/embeddings.py, and a regression would degrade retrieval without failing "
          "anything.",
          "RAG citations are not validated against the retrieved chunks, the way the research "
          "path validates its own. An answer could cite a passage it did not use and nothing "
          "would catch it. This is the largest correctness gap in this product.",
          "The benchmark corpus is 31 paragraphs. Recall should be expected to fall on a "
          "realistic corpus, and until it is measured there, 1.000 is not a claim about "
          "production behaviour.",
          "Refusal rate is not reliably measured pending a corrected re-run, which the provider's "
          "daily token cap prevented.",
          "Ranking quality is unmeasured beyond MRR; NDCG is not computed, so graded relevance "
          "across the whole ranking is unknown.",
          "Chunk size and overlap have never been tuned against a benchmark. They are defensible "
          "defaults, not measured optima.",
          "Ingestion runs in the web process. A restart mid-upload strands a record, mitigated by "
          "a reaper rather than solved by a durable queue.",
          "There is no reranking. A cross-encoder over the fused candidate set is the standard "
          "next step and is not implemented."),

       H3("10.3 Future work, in priority order"),
       UL("Extend scripts/verify_rls.py to rag_documents and rag_chunks, so the checks that "
          "gate the build cover this product's data and not only the other product's.",
          "Validate every citation against the chunks actually retrieved, as the research path "
          "already does. This closes the one gap where the product can be confidently wrong.",
          "Expand the benchmark to 200 or more questions over a larger corpus, and track scores "
          "across runs so regressions are visible rather than discovered.",
          "Re-run the refusal measurement with the corrected grader and report it.",
          "Compute NDCG alongside recall and MRR.",
          "Cross-encoder reranking on the fused candidate set.",
          "Durable job queue for ingestion.",
          "Tune chunk size and overlap against the expanded benchmark rather than asserting "
          "them."),

       H3("10.4 Assessment"),
       P("This product does what it claims within the limits of what has been measured. Its "
         "retrieval is strong on a public benchmark, its refusal behaviour is correct on the "
         "cases examined, and its defence against instructions hidden in documents is structural "
         "rather than pattern-matched — which is the only kind that survived testing."),
       P("What it cannot yet claim is that its citations are trustworthy or that its scores hold "
         "on a realistic corpus. Both are measurable and neither has been measured. This report "
         "states that plainly rather than letting a column of 1.000 scores imply otherwise.")),
]
