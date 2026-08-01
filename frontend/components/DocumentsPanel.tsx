"use client";

import { useCallback, useEffect, useState } from "react";
import { api, JobStatus } from "@/lib/api";

const STATE_STYLE: Record<string, string> = {
  COMPLETED: "bg-emerald-100 text-emerald-700",
  FAILED: "bg-rose-100 text-rose-700",
  RETRYING: "bg-amber-100 text-amber-700",
  PROCESSING: "bg-sky-100 text-sky-700",
  PENDING: "bg-slate-100 text-slate-600",
};

export default function DocumentsPanel() {
  const [jobs, setJobs] = useState<JobStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

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
    const t = setInterval(refresh, 3000); // poll for in-flight jobs
    return () => clearInterval(t);
  }, [refresh]);

  const completed = jobs.filter((j) => j.state === "COMPLETED").length;
  const atCap = completed >= 5;

  async function onUpload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const input = form.elements.namedItem("file") as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    setBusy(true);
    setErr(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      await api.postForm("/ingest/pdf", fd);
      input.value = "";
      refresh();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">My Documents</h2>
        <p className="text-sm text-slate-500">
          Upload PDFs (max 5, ≤10 pages each). Answers in the Ask tab are grounded on these.
        </p>
      </div>

      <div className="card p-5">
        <form onSubmit={onUpload} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label className="label" htmlFor="file">Upload a file</label>
            <input id="file" name="file" type="file" required
              accept=".pdf,.txt,.md,.png,.jpg,.jpeg" className="input file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm file:font-medium file:text-slate-700" />
          </div>
          <button type="submit" disabled={busy || atCap} className="btn-primary">
            {busy ? "Uploading…" : "Upload"}
          </button>
        </form>
        {atCap && (
          <p className="mt-3 text-sm text-amber-700">
            You've reached the 5-document limit. The upload button is disabled.
          </p>
        )}
        {err && <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{err}</p>}
      </div>

      {loading ? (
        <div className="card h-24 animate-pulse bg-slate-100/60" />
      ) : jobs.length === 0 ? (
        <div className="card p-10 text-center text-sm text-slate-500">
          No documents yet. Upload one above.
        </div>
      ) : (
        <div className="card divide-y divide-slate-100">
          {jobs.map((j) => (
            <div key={j.job_id} className="flex items-center justify-between gap-4 p-4">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-900">
                  {filenameOf(j.file_path)}
                </p>
                <p className="text-xs text-slate-400">
                  {j.created_at ? new Date(j.created_at + "Z").toLocaleString() : ""} ·
                  {" "}
                  {j.num_chunks != null ? `${j.num_chunks} chunks` : "—"}
                  {j.error ? ` · ${j.error}` : ""}
                </p>
              </div>
              <span
                className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${
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
