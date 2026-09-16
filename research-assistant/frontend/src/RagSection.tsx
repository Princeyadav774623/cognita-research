import { useState } from "react";
import { DocumentUpload } from "./components/DocumentUpload";
import { ChatPanel } from "./components/ChatPanel";

export function RagSection() {
  const [documentCount, setDocumentCount] = useState(0);

  return (
    <div className="rag-page">
      {/* One page header spanning both columns. It used to live inside the
          chat column only, which pushed that column 83px lower than the
          documents panel beside it and left the row looking misaligned. */}
      <header className="tool-header">
        <div className="tool-header__eyebrow">Grounded In Your Own Sources</div>
        <h2 className="tool-header__title">
          Your documents, <em>answered</em>.
        </h2>
        <p className="tool-header__subtitle">
          Ask questions about the files you upload. Every answer quotes the passage it
          came from, so you can check it.
        </p>
      </header>

      <div className="rag-layout">
        <aside className="rag-sidebar">
          <div className="rag-panel__header">
            <h3 className="rag-panel__title">Knowledge Base</h3>
            <p className="rag-panel__subtitle">
              Upload papers, data sheets, and articles to ask questions about.
            </p>
          </div>
          <DocumentUpload onDocumentsChange={setDocumentCount} />
        </aside>

        <section className="rag-chat">
          <ChatPanel hasDocuments={documentCount > 0} />
        </section>
      </div>
    </div>
  );
}
