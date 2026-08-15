import { useCallback, useEffect, useRef, useState } from "react";
import { uploadDocument, listDocuments, deleteDocument, type RagDocument } from "../ragApi";
import { useAuth } from "../AuthContext";

const STATUS_LABEL: Record<RagDocument["status"], string> = {
  processing: "Processing…",
  ready: "Ready",
  error: "Failed",
};

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

  const handleFileSelect = async (file: File) => {
    if (!accessToken) return;
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
    await deleteDocument(accessToken, id);
    refresh();
  };

  return (
    <div className="doc-upload">
      <label className={`doc-upload__dropzone ${uploading ? "doc-upload__dropzone--busy" : ""}`}>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg"
          disabled={uploading}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFileSelect(file);
          }}
        />
        <span>{uploading ? "Uploading & indexing…" : "Click to upload a PDF, DOCX, TXT, or image"}</span>
      </label>

      {error && <p className="doc-upload__error">⚠ {error}</p>}

      <ul className="doc-list">
        {documents.map((doc) => (
          <li key={doc.id} className={`doc-list__item doc-list__item--${doc.status}`}>
            <div className="doc-list__info">
              <span className="doc-list__name">{doc.filename}</span>
              <span className="doc-list__meta">
                {STATUS_LABEL[doc.status]}
                {doc.status === "ready" && ` · ${doc.chunk_count} chunks`}
                {doc.status === "error" && doc.error && ` · ${doc.error}`}
              </span>
            </div>
            <button className="doc-list__delete" onClick={() => handleDelete(doc.id)}>
              ✕
            </button>
          </li>
        ))}
        {documents.length === 0 && <li className="doc-list__empty">No documents uploaded yet.</li>}
      </ul>
    </div>
  );
}
