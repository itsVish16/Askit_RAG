"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, JobStatus, PresignOut } from "@/lib/api";

const STATE_STYLE: Record<string, string> = {
  COMPLETED: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  FAILED: "bg-red-50 text-red-700 ring-1 ring-red-200",
  RETRYING: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  PROCESSING: "bg-sky-50 text-sky-700 ring-1 ring-sky-200",
  PENDING: "bg-zinc-100 text-zinc-500 ring-1 ring-zinc-200",
};

export default function DocumentsPanel() {
  const [jobs, setJobs] = useState<JobStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const j = await api.get<JobStatus[]>("/ingest/jobs");
      setJobs(j);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, []);

  async function onDelete(jobId: string) {
    if (confirmId === jobId) {
      setDeletingId(jobId);
      try {
        await api.del(`/ingest/jobs/${jobId}`);
        setJobs((prev) => prev.filter((j) => j.job_id !== jobId));
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : "Failed to delete document");
      } finally {
        setDeletingId(null);
        setConfirmId(null);
      }
    } else {
      setConfirmId(jobId);
      setTimeout(() => setConfirmId(null), 3000);
    }
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh]);

  const completed = jobs.filter((j) => j.state === "COMPLETED").length;
  const atCap = completed >= 5;

  async function onUpload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const file = inputRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setErr(null);

    try {
      // Try S3 presigned upload first.
      const presign = await api.post<PresignOut>("/ingest/presign", { filename: file.name }).catch(
        (err: ApiError) => (err.status === 400 ? null : Promise.reject(err))
      );

      if (presign) {
        try {
          const putRes = await fetch(presign.upload_url, {
            method: "PUT",
            body: file,
            headers: { "Content-Type": file.type || "application/octet-stream" },
          });
          if (!putRes.ok) throw new ApiError(putRes.status, "S3 upload failed");
          await api.post("/ingest/s3", { file_key: presign.file_key, filename: file.name });
        } catch (s3Err) {
          console.warn("Direct S3 upload failed (e.g. S3 bucket CORS), falling back to backend upload:", s3Err);
          const fd = new FormData();
          fd.append("file", file);
          await api.postForm("/ingest/pdf", fd);
        }
      } else {
        // Fallback: multipart directly to backend.
        const fd = new FormData();
        fd.append("file", file);
        await api.postForm("/ingest/pdf", fd);
      }

      if (inputRef.current) inputRef.current.value = "";
      refresh();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-zinc-900">Documents</h2>
        <p className="text-sm text-zinc-500">
          Upload PDFs, text, or images. Max 5 documents per account, 10 pages each.
        </p>
      </div>

      <div className="card p-4 sm:p-5">
        <form onSubmit={onUpload} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label className="label" htmlFor="file">Upload a file</label>
            <input
              ref={inputRef}
              id="file"
              name="file"
              type="file"
              required
              accept=".pdf,.txt,.md,.png,.jpg,.jpeg"
              className="input file:mr-3 file:rounded-md file:border-0 file:bg-zinc-100 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-zinc-700 file:cursor-pointer"
            />
          </div>
          <button type="submit" disabled={busy || atCap} className="btn-primary">
            {busy ? "Uploading…" : "Upload"}
          </button>
        </form>
        {atCap && (
          <p className="mt-3 text-sm text-amber-700">
            Document limit reached (5). Remove one before uploading another.
          </p>
        )}
      </div>

      {err && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-600">{err}</p>
      )}

      {loading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="card h-16 animate-pulse bg-zinc-50" />
          ))}
        </div>
      ) : jobs.length === 0 ? (
        <div className="card flex flex-col items-center justify-center py-12 text-center">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="mb-3 text-zinc-300">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          <p className="text-sm text-zinc-500">No documents yet. Upload one above.</p>
        </div>
      ) : (
        <div className="card divide-y divide-zinc-200/60">
          {jobs.map((j) => (
            <div key={j.job_id} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-zinc-900">
                  {filenameOf(j.file_path)}
                </p>
                <p className="text-xs text-zinc-400">
                  {j.created_at ? new Date(j.created_at + "Z").toLocaleString() : ""}
                  {j.num_chunks != null ? ` · ${j.num_chunks} chunk${j.num_chunks === 1 ? "" : "s"}` : ""}
                  {j.error ? ` · ${j.error}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`shrink-0 rounded-md px-2 py-0.5 text-xs font-medium ${
                    STATE_STYLE[j.state || "PENDING"] || STATE_STYLE.PENDING
                  }`}
                >
                  {j.state || "PENDING"}
                </span>
                <button
                  type="button"
                  onClick={() => onDelete(j.job_id)}
                  disabled={deletingId === j.job_id}
                  className={`shrink-0 rounded p-1 text-xs transition-colors ${
                    confirmId === j.job_id
                      ? "bg-red-50 text-red-600 font-semibold ring-1 ring-red-200"
                      : "text-zinc-400 hover:text-red-500 hover:bg-zinc-100"
                  }`}
                  title={confirmId === j.job_id ? "Click again to confirm delete" : "Delete document"}
                >
                  {confirmId === j.job_id ? (
                    "Delete?"
                  ) : (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function filenameOf(path: string | null): string {
  if (!path) return "upload";
  return path.split(/[/\\]/).pop() || path;
}
