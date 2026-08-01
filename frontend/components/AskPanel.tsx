"use client";

import { useState } from "react";
import { api, AskResponse, getSessionId, clearSessionId } from "@/lib/api";

interface Turn {
  question: string;
  answer: string;
  context: string[];
  queries: string[];
  keywords: string[];
}

export default function AskPanel() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showDetails, setShowDetails] = useState<Record<number, boolean>>({});

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setErr(null);
    const q = query;
    setQuery("");
    try {
      const r = await api.post<AskResponse>("/ask", { query: q, session_id: getSessionId() });
      setTurns((t) => [
        ...t,
        { question: q, answer: r.answer, context: r.context, queries: r.queries, keywords: r.keywords },
      ]);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Ask failed");
      setQuery(q); // restore so the user can retry
    } finally {
      setBusy(false);
    }
  }

  function newConversation() {
    clearSessionId();
    setTurns([]);
    setErr(null);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Ask</h2>
          <p className="text-sm text-slate-500">Questions are grounded on your uploaded documents.</p>
        </div>
        {turns.length > 0 && (
          <button onClick={newConversation} className="btn-ghost">New conversation</button>
        )}
      </div>

      <div className="card flex-1 overflow-y-auto p-5">
        {turns.length === 0 ? (
          <div className="flex h-full items-center justify-center text-center text-sm text-slate-400">
            Ask your first question below.
          </div>
        ) : (
          <div className="space-y-6">
            {turns.map((t, i) => (
              <div key={i} className="space-y-3">
                <div className="flex justify-end">
                  <span className="max-w-[80%] rounded-2xl bg-brand-600 px-4 py-2.5 text-sm text-white">
                    {t.question}
                  </span>
                </div>
                <div className="rounded-2xl bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-800 whitespace-pre-wrap">
                  {t.answer}
                </div>
                <button
                  onClick={() => setShowDetails((s) => ({ ...s, [i]: !s[i] }))}
                  className="text-xs font-medium text-brand-600 hover:text-brand-700"
                >
                  {showDetails[i] ? "Hide retrieval details" : `Show retrieval details (${t.context.length} chunks)`}
                </button>
                {showDetails[i] && (
                  <div className="space-y-3 rounded-xl bg-slate-50 p-4 text-xs">
                    <Detail label="Expanded queries" items={t.queries} />
                    <Detail label="Keywords" items={t.keywords} />
                    <div>
                      <p className="mb-1 font-semibold text-slate-600">Context chunks</p>
                      <ol className="list-decimal space-y-1 pl-5 text-slate-500">
                        {t.context.map((c, ci) => (
                          <li key={ci} className="leading-relaxed">{c}</li>
                        ))}
                      </ol>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {err && <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{err}</p>}

      <form onSubmit={ask} className="mt-4 flex gap-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask a question about your documents…"
          className="input"
          disabled={busy}
        />
        <button type="submit" disabled={busy || !query.trim()} className="btn-primary shrink-0">
          {busy ? "Thinking…" : "Send"}
        </button>
      </form>
    </div>
  );
}

function Detail({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="mb-1 font-semibold text-slate-600">{label}</p>
      <div className="flex flex-wrap gap-1.5">
        {items.map((x, i) => (
          <span key={i} className="rounded-md bg-white px-2 py-0.5 text-slate-600 ring-1 ring-slate-200">
            {x}
          </span>
        ))}
      </div>
    </div>
  );
}
