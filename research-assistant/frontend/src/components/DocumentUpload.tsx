import { useCallback, useEffect, useRef, useState } from "react";
import { uploadDocument, listDocuments, deleteDocument, type RagDocument } from "../ragApi";
import { useAuth } from "../AuthContext";
import { Icon } from "./Icon";

const STATUS_LABEL: Record<RagDocument["status"], string> = {
  processing: "Indexing…",
  ready: "Ready",
  error: "Failed",
};

// Mirrors MAX_FILE_SIZE_BYTES in backend/rag/ingest.py and client_max_body_size
// in frontend/nginx.conf. Checked here purely so an oversized file is rejected
// instantly instead of after a long upload that the server will refuse anyway.
const MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024;

interface Props {
  onDocumentsChange: (count: number) => void;
}

export function DocumentUpload({ onDocumentsChange }: Props) {
  const { accessToken } = useAuth();
  const [documents, setDocuments] = useState<RagDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    if (!accessToken) return;
    listDocuments(accessToken)
      .then((docs) => {
        setDocuments(docs);
        onDocumentsChange(docs.filter((d) => d.status === "ready").length);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load documents"));
  }, [accessToken, onDocumentsChange]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Indexing now happens after the upload response returns, so the row starts
  // at "processing" and nothing would ever move it off that label without
  // asking again. Polls only while something is actually in flight.
  const anyProcessing = documents.some((d) => d.status === "processing");
  useEffect(() => {
    if (!anyProcessing) return;
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
  }, [anyProcessing, refresh]);

  const handleFileSelect = async (file: File) => {
    if (!accessToken) return;
    if (file.size > MAX_FILE_SIZE_BYTES) {
      setError(
        `"${file.name}" is ${(file.size / 1024 / 1024).toFixed(1)}MB — the limit is 15MB.`
      );
      if (inputRef.current) inputRef.current.value = "";
      return;
    }
    setUploading(true);
    setError(null);
    try {
      await uploadDocument(accessToken, file);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handleDelete = async (id: string) => {
    if (!accessToken) return;
    try {
      await deleteDocument(accessToken, id);
      refresh();
    } catch {
      // Handle error
    }
  };

  return (
    <div>
      <label className={`rag-dropzone ${uploading ? "rag-dropzone--active" : ""}`} style={{ display: "block" }}>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg"
          disabled={uploading}
          style={{ display: "none" }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFileSelect(file);
          }}
        />
        <div style={{ marginBottom: "0.6rem", color: "var(--accent-warm)", display: "flex", justifyContent: "center" }}>
          <Icon name={uploading ? "clock" : "upload"} size={26} />
        </div>
        <div style={{ fontWeight: 600, fontSize: "0.9rem", color: "var(--text-primary)", marginBottom: "0.2rem" }}>
          {uploading ? "Processing & Vectorizing..." : "Drop or Choose Files"}
        </div>
        <div style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
          PDF, DOCX, TXT, MD, Images
        </div>
      </label>

      {error && (
        <div className="auth-card__error" style={{ marginBottom: "1rem" }}>
          <Icon name="alert" size={15} /> {error}
        </div>
      )}

      <div className="rag-doc-list">
        {documents.map((doc) => (
          <div key={doc.id} className="rag-doc-item">
            <div style={{ minWidth: 0, flex: 1, marginRight: "0.5rem" }}>
              <div style={{ fontWeight: 500, fontSize: "0.85rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {doc.filename}
              </div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--text-muted)" }}>
                {STATUS_LABEL[doc.status]}
                {doc.status === "ready" && ` · ${doc.chunk_count} chunks`}
              </div>
            </div>
            <button
              type="button"
              className="history-item__delete"
              onClick={() => handleDelete(doc.id)}
              title="Remove document"
            >
              <Icon name="trash" size={14} />
            </button>
          </div>
        ))}
        {documents.length === 0 && (
          <div style={{ color: "var(--text-muted)", fontSize: "0.82rem", textAlign: "center", padding: "1rem 0" }}>
            No documents in knowledge base yet.
          </div>
        )}
      </div>
    </div>
  );
}
