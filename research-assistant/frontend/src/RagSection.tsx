import { useState } from "react";
import { DocumentUpload } from "./components/DocumentUpload";
import { ChatPanel } from "./components/ChatPanel";

export function RagSection() {
  const [documentCount, setDocumentCount] = useState(0);

  return (
    <div className="app__main">
      <section className="app__panel app__panel--primary">
        <h2 className="rag-section__title">Chat with your files</h2>
        <p className="rag-section__subtitle">
          Upload documents and ask questions — answers are grounded in what you upload, with citations.
        </p>
        <ChatPanel hasDocuments={documentCount > 0} />
      </section>

      <aside className="app__panel app__panel--sidebar">
        <h3>Documents</h3>
        <DocumentUpload onDocumentsChange={setDocumentCount} />
      </aside>
    </div>
  );
}
