"use client";

import { useEffect, useState } from "react";
import { api, EvalResults } from "@/lib/api";

const METRICS: { key: string; label: string; description: string; higherBetter: boolean }[] = [
  { key: "hallucination", label: "Hallucination", description: "Fabricated content in answers", higherBetter: false },
  { key: "answer_relevance", label: "Answer Relevance", description: "How well answers address the question", higherBetter: true },
  { key: "context_recall", label: "Context Recall", description: "Correct info retrieved from documents", higherBetter: true },
  { key: "context_precision", label: "Context Precision", description: "Signal-to-noise in retrieved chunks", higherBetter: true },
];

function scoreColor(pct: number, higherBetter: boolean) {
  const good = higherBetter ? pct >= 70 : pct <= 30;
  const ok = higherBetter ? pct >= 45 : pct <= 55;
  if (good) return "bg-emerald-500";
  if (ok) return "bg-amber-500";
  return "bg-red-500";
}

export default function EvalPanel() {
  const [data, setData] = useState<EvalResults | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "empty" | "error">("loading");

  useEffect(() => {
    api
      .get<EvalResults>("/eval/results")
      .then((r) => {
        setData(r);
        setStatus("ready");
      })
      .catch((e: { status?: number }) => {
        setStatus(e?.status === 404 ? "empty" : "error");
      });
  }, []);

  if (status === "loading") {
    return (
      <div>
        <div className="mb-6">
          <div className="h-5 w-48 animate-pulse rounded bg-surface-200" />
          <div className="mt-1 h-4 w-64 animate-pulse rounded bg-surface-100" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card h-28 animate-pulse bg-surface-50" />
          ))}
        </div>
      </div>
    );
  }

  if (status === "empty") {
    return (
      <div className="card flex flex-col items-center justify-center py-12 text-center">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="mb-3 text-slate-300">
          <path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-4 0v-5" />
          <path d="M12 12h.01" />
          <path d="M2 14h4" />
        </svg>
        <h3 className="text-base font-medium text-slate-700">No eval run yet</h3>
        <p className="mt-1 text-sm text-slate-500">Run the COVID-QA eval on the backend:</p>
        <pre className="mt-3 rounded-md bg-slate-900 px-4 py-2 text-sm text-slate-100">uv run python -m app.evaluation.evals</pre>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="card flex flex-col items-center justify-center py-12 text-center">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="mb-3 text-slate-300">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <h3 className="text-base font-medium text-slate-700">Couldn't load results</h3>
        <p className="mt-1 text-sm text-slate-500">Is the backend running?</p>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-base font-semibold text-slate-800">COVID-QA Experiment</h2>
        <p className="text-sm text-slate-500">
          Last run {new Date(data!.created_at + "Z").toLocaleString()} · 50 test questions · LLM-as-a-Judge
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {METRICS.map((m) => {
          const raw = data!.metrics[m.key] ?? 0;
          const pct = Math.round(Math.max(0, Math.min(1, raw)) * 100);
          return (
            <div key={m.key} className="card p-5">
              <div className="flex items-baseline justify-between gap-2">
                <div>
                  <span className="text-sm font-medium text-slate-600">{m.label}</span>
                  <p className="text-xs text-slate-400">{m.description}</p>
                </div>
                <span className="shrink-0 text-2xl font-semibold tabular-nums text-slate-800">
                  {raw.toFixed(3)}
                </span>
              </div>
              <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-surface-100">
                <div
                  className={`h-full rounded-full transition-all ${scoreColor(pct, m.higherBetter)}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
