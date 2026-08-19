import { useState } from "react";
import { DocumentUpload } from "./components/DocumentUpload";
import { ChatPanel } from "./components/ChatPanel";

export function RagSection() {
  const [documentCount, setDocumentCount] = useState(0);

  return (
    <div className="rag-layout">
      <aside className="rag-sidebar">
        <div style={{ marginBottom: "1.25rem", borderBottom: "1px solid var(--border-subtle)", paddingBottom: "0.75rem" }}>
          <h3 style={{ fontFamily: "var(--font-serif)", fontSize: "1.2rem", margin: "0 0 0.35rem" }}>
            Knowledge Base
          </h3>
          <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", margin: 0 }}>
            Upload research papers, data sheets, and articles for verified Q&A.
          </p>
        </div>
        <DocumentUpload onDocumentsChange={setDocumentCount} />
      </aside>

      <section className="rag-chat">
        <div style={{ marginBottom: "1.25rem", borderBottom: "1px solid var(--border-subtle)", paddingBottom: "0.75rem" }}>
          <h2 style={{ fontFamily: "var(--font-serif)", fontSize: "1.45rem", margin: "0 0 0.25rem" }}>
            Chat with Documents
          </h2>
          <p style={{ fontSize: "0.88rem", color: "var(--text-secondary)", margin: 0 }}>
            Every response is strictly grounded in the document context with inline citations.
          </p>
        </div>
        <ChatPanel hasDocuments={documentCount > 0} />
      </section>
    </div>
  );
}
