# Data Processing Agreement (DPA)

**Effective Date: August 2026**

This Data Processing Addendum ("DPA") supplements the Terms of Service between **Customer** ("Data Controller") and **Multi-Agent Deep Research Platform** ("Data Processor").

---

## 1. Scope and Processing of Personal Data
1. **Subject Matter**: Providing autonomous AI deep research, web retrieval, document parsing, and RAG semantic search.
2. **Categories of Data**: User queries, customer-uploaded documents, synthesis outputs, and access identifiers.
3. **Purpose of Processing**: Executing agent tasks requested directly by the Data Controller.

---

## 2. Technical and Organizational Security Measures
1. **Multi-Tenant Isolation**: Data is separated via PostgreSQL Row-Level Security (RLS) policies and user-scoped tenant sessions.
2. **Encryption**: All data in transit is encrypted using TLS 1.3; data at rest is encrypted using AES-256.
3. **Zero Model Training**: Customer Data is never used to train or fine-tune public foundational AI models.
4. **Data Deletion Rights**: Data Controller may execute automated permanent deletion of all stored documents, embeddings, and chat histories via `DELETE /api/user/me`.

---

## 3. Sub-Processors
The Data Processor utilizes the following vetted sub-processors for infrastructure:
- **Supabase / AWS**: Database, vector storage, and user authentication.
- **Groq Inc.**: High-speed inference (under strict zero-retention commercial terms).
- **Tavily Technologies**: Web search API for source retrieval.
- **Stripe Inc.**: PCI-DSS compliant billing processing.
