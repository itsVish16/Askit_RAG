"use client";

import { useEffect, useState } from "react";
import { api, EvalResults } from "@/lib/api";

const METRICS: { key: string; label: string; higherBetter: boolean }[] = [
  { key: "hallucination", label: "Hallucination", higherBetter: false },
  { key: "answer_relevance", label: "Answer Relevance", higherBetter: true },
  { key: "context_recall", label: "Context Recall", higherBetter: true },
  { key: "context_precision", label: "Context Precision", higherBetter: true },
];

function scoreColor(pct: number, higherBetter: boolean) {
  // pct is 0..100 of the metric value. Good = green when higher-better & high,
  // or lower-better & low.
  const good = higherBetter ? pct >= 70 : pct <= 30;
  const ok = higherBetter ? pct >= 45 : pct <= 55;
  if (good) return "from-emerald-400 to-emerald-500";
  if (ok) return "from-amber-400 to-amber-500";
  return "from-rose-400 to-rose-500";
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

  if (status === "loading") return <Skeleton />;
  if (status === "empty")
    return (
      <EmptyState
        title="No eval run yet"
        body="Run the COVID-QA eval on the backend to populate this view:"
        code="uv run python -m app.evaluation.evals"
      />
    );
  if (status === "error")
    return <EmptyState title="Couldn't load results" body="Is the backend running on port 3001?" />;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">COVID-QA Experiment</h2>
          <p className="text-sm text-slate-500">
            Last run {new Date(data!.created_at + "Z").toLocaleString()} · 50 test questions ·
            LLM-as-a-Judge
          </p>
        </div>
      </div>

      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {METRICS.map((m) => {
          const raw = data!.metrics[m.key] ?? 0;
          const pct = Math.round(Math.max(0, Math.min(1, raw)) * 100);
          return (
            <div key={m.key} className="card p-5">
              <div className="flex items-baseline justify-between">
                <span className="text-sm font-medium text-slate-500">{m.label}</span>
                <span className="text-2xl font-bold tabular-nums text-slate-900">
                  {raw.toFixed(3)}
                </span>
              </div>
              <div className="mt-4 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
                <div
                  className={`h-full rounded-full bg-gradient-to-r ${scoreColor(pct, m.higherBetter)}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-slate-400">
                {m.higherBetter ? "Higher is better" : "Lower is better"}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="card h-32 animate-pulse bg-slate-100/60" />
      ))}
    </div>
  );
}

function EmptyState({ title, body, code }: { title: string; body: string; code?: string }) {
  return (
    <div className="card flex flex-col items-center justify-center p-12 text-center">
      <div className="mb-4 h-12 w-12 rounded-2xl bg-slate-100" />
      <h3 className="text-base font-semibold text-slate-900">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-slate-500">{body}</p>
      {code && (
        <pre className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm text-slate-100">{code}</pre>
      )}
    </div>
  );
}
