"use client";

import { useCallback, useState, useRef } from "react";

interface DocumentMeta {
  document_type: string;
  department: string;
  author: string;
  effective_date: string;
}

interface IngestResult {
  status: string;
  filename: string;
  content_type: string;
  format: string | null;
  size_bytes: number;
  total_chunks: number;
  envelope_ids: string[];
  routing_results: any[];
}

interface RecentUpload {
  filename: string;
  chunks: number;
  format: string | null;
  timestamp: Date;
  envelopeIds: string[];
}

const SUPPORTED_FORMATS = [
  { ext: "PDF", desc: "Adobe PDF documents" },
  { ext: "TXT", desc: "Plain text files" },
  { ext: "CSV", desc: "Comma-separated values" },
  { ext: "MD", desc: "Markdown documents" },
  { ext: "DOCX", desc: "Word documents" },
  { ext: "CDA/CCD", desc: "HL7 Clinical Document Architecture" },
];

const DOC_TYPES = ["", "policy", "procedure", "guideline", "protocol", "compliance", "form"];

const API_BASE = process.env.NEXT_PUBLIC_TRELLIS_API_URL || "";

export default function DocumentsPage() {
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestResult | null>(null);
  const [recent, setRecent] = useState<RecentUpload[]>([]);
  const [meta, setMeta] = useState<DocumentMeta>({ document_type: "", department: "", author: "", effective_date: "" });
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback((file: File) => {
    setSelectedFile(file);
    setError(null);
    setResult(null);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const handleUpload = useCallback(async () => {
    if (!selectedFile) return;
    setUploading(true);
    setError(null);
    setResult(null);

    const formData = new FormData();
    formData.append("file", selectedFile);
    if (meta.document_type) formData.append("document_type", meta.document_type);
    if (meta.department) formData.append("department", meta.department);
    if (meta.author) formData.append("author", meta.author);
    if (meta.effective_date) formData.append("effective_date", meta.effective_date);

    try {
      const res = await fetch(`${API_BASE}/api/documents/ingest`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const data: IngestResult = await res.json();
      setResult(data);
      setRecent(prev => [{
        filename: data.filename,
        chunks: data.total_chunks,
        format: data.format,
        timestamp: new Date(),
        envelopeIds: data.envelope_ids,
      }, ...prev].slice(0, 20));
      setSelectedFile(null);
      setMeta({ document_type: "", department: "", author: "", effective_date: "" });
      if (fileRef.current) fileRef.current.value = "";
    } catch (err: any) {
      setError(err.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  }, [selectedFile, meta]);

  const inputClass = "bg-muted/10 border border-border rounded-md px-3 py-1.5 text-xs text-foreground/80 placeholder-muted-foreground outline-none focus:border-primary/40 focus:ring-1 focus:ring-primary/20 transition-colors w-full";

  return (
    <div className="space-y-4">
      {/* Upload Zone */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-border">
          <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium">Document Ingestion</span>
        </div>
        <div className="p-4 space-y-4">
          {/* Drop zone */}
          <div
            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
            className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
              dragOver ? "border-primary/60 bg-primary/5" :
              selectedFile ? "border-status-healthy/40 bg-status-healthy/5" :
              "border-border hover:border-border bg-muted/5"
            }`}
          >
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept=".pdf,.txt,.csv,.md,.docx,.xml"
              onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
            />
            {selectedFile ? (
              <div>
                <p className="text-sm text-status-healthy font-medium">{selectedFile.name}</p>
                <p className="text-xs text-muted-foreground mt-1">{(selectedFile.size / 1024).toFixed(1)} KB — click to change</p>
              </div>
            ) : (
              <div>
                <p className="text-sm text-muted-foreground">Drop a document here or click to browse</p>
                <p className="text-xs text-muted-foreground mt-1">PDF, TXT, CSV, MD, DOCX, HL7 CDA/CCD — max 10MB</p>
              </div>
            )}
          </div>

          {/* Metadata fields */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div>
              <label className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1 block">Document Type</label>
              <select
                value={meta.document_type}
                onChange={e => setMeta(m => ({ ...m, document_type: e.target.value }))}
                className={inputClass}
              >
                <option value="">— optional —</option>
                {DOC_TYPES.filter(Boolean).map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1 block">Department</label>
              <input placeholder="e.g. Nursing" value={meta.department} onChange={e => setMeta(m => ({ ...m, department: e.target.value }))} className={inputClass} />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1 block">Author</label>
              <input placeholder="e.g. J. Smith" value={meta.author} onChange={e => setMeta(m => ({ ...m, author: e.target.value }))} className={inputClass} />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1 block">Effective Date</label>
              <input type="date" value={meta.effective_date} onChange={e => setMeta(m => ({ ...m, effective_date: e.target.value }))} className={inputClass} />
            </div>
          </div>

          {/* Upload button */}
          <div className="flex items-center gap-3">
            <button
              onClick={handleUpload}
              disabled={!selectedFile || uploading}
              className="px-4 py-1.5 rounded-md text-xs font-medium transition-colors bg-primary/15 text-primary hover:bg-primary/25 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              {uploading ? "Ingesting…" : "Ingest Document"}
            </button>
            {error && <span className="text-xs text-destructive">{error}</span>}
          </div>
        </div>
      </div>

      {/* Supported Formats */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-border">
          <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium">Supported Formats</span>
        </div>
        <div className="px-4 py-3 flex flex-wrap gap-2">
          {SUPPORTED_FORMATS.map(f => (
            <div key={f.ext} className="flex items-center gap-2 px-2.5 py-1 rounded bg-muted/10 border border-border">
              <span className="text-xs font-medium text-primary font-data">{f.ext}</span>
              <span className="text-[10px] text-muted-foreground">{f.desc}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Results */}
      {result && (
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border flex items-center gap-2">
            <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium">Ingestion Result</span>
            <span className={`status-dot ${result.status === "ok" ? "status-dot-healthy" : "status-dot-unhealthy"}`} />
          </div>
          <div className="p-4 space-y-3">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">File</p>
                <p className="text-xs text-foreground/80 font-data mt-0.5">{result.filename}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Format</p>
                <p className="text-xs text-foreground/80 font-data mt-0.5">{result.format || result.content_type}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Size</p>
                <p className="text-xs text-foreground/80 font-data mt-0.5">{(result.size_bytes / 1024).toFixed(1)} KB</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Chunks</p>
                <p className="text-xs text-status-healthy font-data mt-0.5">{result.total_chunks}</p>
              </div>
            </div>
            {/* Envelope IDs */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">Envelope IDs</p>
              <div className="max-h-32 overflow-y-auto space-y-0.5">
                {result.envelope_ids.map((id, i) => (
                  <div key={id} className="flex items-center gap-2">
                    <span className="text-[10px] text-muted-foreground w-6 text-right">{i + 1}</span>
                    <span className="text-[10px] text-muted-foreground font-data">{id}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Recent Uploads */}
      {recent.length > 0 && (
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border">
            <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium">Recent Uploads</span>
            <span className="text-xs text-muted-foreground ml-2">({recent.length})</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground uppercase border-b border-border">
                  <th className="text-left px-3 py-2">File</th>
                  <th className="text-left px-3 py-2">Format</th>
                  <th className="text-right px-3 py-2">Chunks</th>
                  <th className="text-right px-3 py-2">When</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((r, i) => (
                  <tr key={i} className="table-row-hover">
                    <td className="px-3 py-2 text-xs text-foreground/80 font-data">{r.filename}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">{r.format || "—"}</td>
                    <td className="px-3 py-2 text-right text-xs text-status-healthy font-data">{r.chunks}</td>
                    <td className="px-3 py-2 text-right text-xs text-muted-foreground">{r.timestamp.toLocaleTimeString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
