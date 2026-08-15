# Privacy Policy

**Last Updated: August 2026**

This Privacy Policy explains how the **Multi-Agent Deep Research Platform** collects, uses, and safeguards your data.

---

## 1. Information We Collect
- **Account Identifiers**: User ID, email, and authentication tokens managed via secure Supabase Auth / JWTs.
- **User Inputs**: Search queries, research topics, and uploaded documents (PDFs, DOCX, TXT, MD, Images).
- **Generated Data**: Agent session graphs, synthesis drafts, fact-check ratings, and vector embeddings generated via FastEmbed / pgvector.

---

## 2. How Your Data Is Processed
- **No Training on Private Data**: Uploaded user documents and queries are used strictly to serve real-time RAG context and agent research workflows. They are never used to train public foundational AI models.
- **Third-Party Model Processors**: Query text is dispatched to model providers (Groq, Tavily, Cohere) strictly under zero-data-retention commercial inference agreements.

---

## 3. Data Isolation & Security (Row-Level Security)
- All user data is partitioned with strict PostgreSQL **Row-Level Security (RLS)** and tenant-scoped connection pools. No user can view, query, or search another user's documents or research sessions.

---

## 4. GDPR & Data Subject Rights
Under GDPR and CCPA, you have the right to:
1. **Access & Export**: View and copy your complete research history.
2. **Right to Erasure ("Right to Be Forgotten")**: Permanently delete your account, documents, vector chunks, and messages with one click via `DELETE /api/user/me`.
