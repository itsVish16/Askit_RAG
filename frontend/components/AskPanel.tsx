"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getSessionId,
  setSessionId,
  askStream,
  StreamEvent,
  getMessages,
  ChatMessage,
} from "@/lib/api";
import { newConversation } from "@/lib/sessions";
import { generateUUID } from "@/lib/uuid";

interface Turn {
  id: string;
  question: string;
  answer: string;
  /** Streaming: answer built up token-by-token. */
  isStreaming: boolean;
  context: string[];
  queries: string[];
}

export default function AskPanel({ refreshKey }: { refreshKey?: number }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showDetails, setShowDetails] = useState<Record<string, boolean>>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const aborter = useRef<AbortController | null>(null);

  // Load messages from server on mount.
  useEffect(() => {
    const sid = getSessionId();
    if (!sid) return;
    getMessages(sid)
      .then((msgs) => {
        if (msgs.length === 0) return;
        const loaded: Turn[] = [];
        for (let i = 0; i < msgs.length; i += 2) {
          const human = msgs[i];
          const ai = msgs[i + 1];
          if (human && human.role === "human") {
            loaded.push({
              id: generateUUID(),
              question: human.content,
              answer: ai?.content || "",
              isStreaming: false,
              context: ai?.context ? safeParseList(ai.context) : [],
              queries: ai?.queries ? safeParseList(ai.queries) : [],
            });
          }
        }
        setTurns(loaded);
      })
      .catch(() => {});
  }, [refreshKey]);

  // Auto-scroll.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q || busy) return;
    setErr(null);
    setQuery("");

    const turnId = generateUUID();
    const newTurn: Turn = {
      id: turnId,
      question: q,
      answer: "",
      isStreaming: true,
      context: [],
      queries: [],
    };

    // Show user bubble + empty answer bubble immediately.
    setTurns((prev) => [...prev, newTurn]);
    setBusy(true);

    const sid = getSessionId();
    console.log(`[AskPanel] askStream START. sid=${sid}, query="${q}"`);

    aborter.current = askStream(
      q,
      sid,
      (evt: StreamEvent) => {
        if (evt.event === "session" && evt.session_id) {
          console.log(`[AskPanel] session event received: ${evt.session_id}`);
          setSessionId(evt.session_id);
        } else if (evt.event === "token" && evt.token) {
          // Log only occasionally to avoid spam
          if (evt.token.length < 10) {
            console.log(`[AskPanel] first token received: "${evt.token}"`);
          }
          // Update the streaming answer text.
          setTurns((prev) =>
            prev.map((t) =>
              t.id === turnId ? { ...t, answer: evt.token || "" } : t
            )
          );
        } else if (evt.event === "done") {
          console.log(`[AskPanel] DONE event received. Final answer length: ${evt.answer?.length}`);
          // Finalize the turn.
          setTurns((prev) =>
            prev.map((t) =>
              t.id === turnId
                ? {
                    ...t,
                    answer: evt.answer || t.answer,
                    isStreaming: false,
                    context: evt.context || [],
                    queries: evt.queries || [],
                  }
                : t
            )
          );
          setBusy(false);
          console.log(`[AskPanel] Dispatching askit:session-updated (DONE)`);
          window.dispatchEvent(new CustomEvent("askit:session-updated"));
        }
      },
      (error: Error) => {
        console.error(`[AskPanel] onError triggered:`, error);
        setErr(error.message);
        setTurns((prev) =>
          prev.map((t) =>
            t.id === turnId ? { ...t, isStreaming: false } : t
          )
        );
        setBusy(false);
        console.log(`[AskPanel] Dispatching askit:session-updated (ERROR)`);
        window.dispatchEvent(new CustomEvent("askit:session-updated"));
      },
      () => {
        console.log(`[AskPanel] onDone callback (connection closed)`);
        setBusy(false);
      }
    );
  }

  function handleNewConversation() {
    if (aborter.current) aborter.current.abort();
    newConversation();
    setTurns([]);
    setErr(null);
    setShowDetails({});
  }

  return (
    <div className="flex h-full flex-col">
      {/* header */}
      <div className="flex items-center justify-between pb-3">
        <div>
          <h2 className="text-base font-semibold text-zinc-900">Ask</h2>
          <p className="text-sm text-zinc-500">
            Questions grounded on your uploaded documents.
          </p>
        </div>
        {turns.length > 0 && (
          <button onClick={handleNewConversation} className="btn-ghost text-xs">
            New conversation
          </button>
        )}
      </div>

      {/* error */}
      {err && (
        <p className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-600">
          {err}
        </p>
      )}

      {/* chat area */}
      <div className="card flex-1 overflow-y-auto">
        <div className="flex flex-col gap-4 p-4 sm:p-6">
          {turns.length === 0 ? (
            <div className="flex h-full min-h-[24rem] items-center justify-center text-center text-sm text-zinc-400">
              Ask a question to get started.
            </div>
          ) : (
            turns.map((t) => (
              <div key={t.id} className="space-y-2">
                {/* user bubble */}
                <div className="flex justify-end">
                  <div className="max-w-[75%] rounded-lg bg-zinc-900 px-4 py-3 text-sm text-white shadow-sm leading-relaxed">
                    {t.question}
                  </div>
                </div>

                {/* answer bubble */}
                <div>
                  {t.isStreaming && !t.answer ? (
                    /* typing indicator while waiting for first tokens */
                    <div className="flex items-start gap-2">
                      <div className="rounded-lg bg-white px-4 py-3 border border-zinc-200/60 shadow-sm">
                        <span className="dot" />
                        <span className="dot" />
                        <span className="dot" />
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div className="rounded-lg bg-white px-4 py-3 border border-zinc-200/60 shadow-sm text-sm leading-relaxed text-zinc-800 whitespace-pre-wrap">
                        {t.answer}
                        {t.isStreaming && <span className="cursor-blink" />}
                      </div>

                      {/* retrieval details */}
                      {!t.isStreaming && t.queries.length > 0 && (
                        <button
                          onClick={() =>
                            setShowDetails((s) => ({
                              ...s,
                              [t.id]: !s[t.id],
                            }))
                          }
                          className="mt-1 text-xs font-medium text-brand-600 hover:text-brand-700 font-semibold"
                        >
                          {showDetails[t.id]
                            ? "Hide retrieval details"
                            : `Show retrieval details (${t.context.length} chunks)`}
                        </button>
                      )}
                      {showDetails[t.id] && !t.isStreaming && (
                        <div className="mt-2 space-y-2 rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-xs">
                          {t.queries.length > 0 && (
                            <div>
                              <p className="mb-1 font-medium text-zinc-600">
                                Search queries
                              </p>
                              <div className="flex flex-wrap gap-1.5">
                                {t.queries.map((x, ci) => (
                                  <span
                                    key={ci}
                                    className="rounded bg-white px-2 py-0.5 text-zinc-600 ring-1 ring-zinc-200"
                                  >
                                    {x}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                          {t.context.length > 0 && (
                            <div>
                              <p className="mb-1 font-medium text-zinc-600">
                                Context chunks
                              </p>
                              <ol className="list-decimal space-y-1 pl-5 text-zinc-500">
                                {t.context.map((c, ci) => (
                                  <li key={ci} className="leading-relaxed">
                                    {c}
                                  </li>
                                ))}
                              </ol>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* chat input - Perplexity style unified pill */}
      <div className="pt-2 pb-4">
        <form 
          onSubmit={ask} 
          className="relative flex items-center rounded-2xl bg-white border border-zinc-200/80 shadow-sm focus-within:border-brand-500 focus-within:ring-1 focus-within:ring-brand-500 transition-all overflow-hidden"
        >
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask a question about your documents..."
            className="flex-1 bg-transparent px-4 py-3.5 text-sm text-zinc-800 placeholder-zinc-400 focus:outline-none disabled:opacity-50"
            disabled={busy}
          />
          <div className="pr-2">
            <button
              type="submit"
              disabled={busy || !query.trim()}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-zinc-900 text-white transition-transform hover:scale-105 disabled:opacity-30 disabled:hover:scale-100"
            >
              {busy ? (
                <svg className="h-4 w-4 animate-spin text-white" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M5 12h14" />
                  <path d="m12 5 7 7-7 7" />
                </svg>
              )}
            </button>
          </div>
        </form>
      </div>

      <style jsx>{`
        .dot {
          display: inline-block;
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: #a1a1aa;
          margin-right: 3px;
          animation: blink 1.4s infinite both;
        }
        .dot:nth-child(2) {
          animation-delay: 0.2s;
        }
        .dot:nth-child(3) {
          animation-delay: 0.4s;
        }
        @keyframes blink {
          0%,
          80%,
          100% {
            opacity: 0.3;
          }
          40% {
            opacity: 1;
          }
        }
        .cursor-blink::after {
          content: "▊";
          animation: pulse 1s infinite;
          color: #0284c7;
          margin-left: 1px;
        }
        @keyframes pulse {
          0%,
          100% {
            opacity: 1;
          }
          50% {
            opacity: 0;
          }
        }
      `}</style>
    </div>
  );
}

function safeParseList(raw: string): string[] {
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}
