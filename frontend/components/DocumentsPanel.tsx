"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, JobStatus, PresignOut } from "@/lib/api";

const STATE_STYLE: Record<string, string> = {
  COMPLETED: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  FAILED: "bg-red-50 text-red-700 ring-1 ring-red-200",
  RETRYING: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  PROCESSING: "bg-sky-50 text-sky-700 ring-1 ring-sky-200",
  PENDING: "bg-surface-100 text-slate-500 ring-1 ring-surface-200",
};

export default function DocumentsPanel() {
  const [jobs, setJobs] = useState<JobStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
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
        const putRes = await fetch(presign.upload_url, {
          method: "PUT",
          body: file,
          headers: { "Content-Type": file.type || "application/octet-stream" },
        });
        if (!putRes.ok) throw new ApiError(putRes.status, "S3 upload failed");
        await api.post("/ingest/s3", { file_key: presign.file_key, filename: file.name });
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
        <h2 className="text-base font-semibold text-slate-800">Documents</h2>
        <p className="text-sm text-slate-500">
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
              className="input file:mr-3 file:rounded-md file:border-0 file:bg-surface-100 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-slate-700 file:cursor-pointer"
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
            <div key={i} className="card h-16 animate-pulse bg-surface-50" />
          ))}
        </div>
      ) : jobs.length === 0 ? (
        <div className="card flex flex-col items-center justify-center py-12 text-center">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="mb-3 text-slate-300">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          <p className="text-sm text-slate-500">No documents yet. Upload one above.</p>
        </div>
      ) : (
        <div className="card divide-y divide-surface-100">
          {jobs.map((j) => (
            <div key={j.job_id} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-800">
                  {filenameOf(j.file_path)}
                </p>
                <p className="text-xs text-slate-400">
                  {j.created_at ? new Date(j.created_at + "Z").toLocaleString() : ""}
                  {j.num_chunks != null ? ` · ${j.num_chunks} chunk${j.num_chunks === 1 ? "" : "s"}` : ""}
                  {j.error ? ` · ${j.error}` : ""}
                </p>
              </div>
              <span
                className={`shrink-0 rounded-md px-2 py-0.5 text-xs font-medium ${
                  STATE_STYLE[j.state || "PENDING"] || STATE_STYLE.PENDING
                }`}
              >
                {j.state || "PENDING"}
              </span>
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
