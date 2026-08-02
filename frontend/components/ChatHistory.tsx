"use client";

import { useEffect, useState } from "react";
import { ChatSession, deleteSession as apiDeleteSession } from "@/lib/api";
import { getSessions } from "@/lib/sessions";

interface Props {
  activeSessionId: string | null;
  onSelect: (id: string) => void;
  /** Refresh counter — bumped when parent needs a re-fetch. */
  refreshKey: number;
}

export default function ChatHistory({ activeSessionId, onSelect, refreshKey }: Props) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getSessions()
      .then(setSessions)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [refreshKey]);

  async function handleDelete(sid: string) {
    if (confirmId === sid) {
      try {
        await apiDeleteSession(sid);
      } catch {
        /* proceed with local removal anyway */
      }
      setSessions((prev) => prev.filter((s) => s.id !== sid));
      setConfirmId(null);
    } else {
      setConfirmId(sid);
      setTimeout(() => setConfirmId(null), 3000);
    }
  }

  return (
    <div className="mt-6 border-t border-surface-100 pt-4">
      <p className="mb-2 px-3 text-xs font-medium uppercase tracking-wider text-slate-400">
        Chat history
      </p>

      {loading ? (
        <div className="space-y-1 px-3">
          {[1, 2].map((i) => (
            <div key={i} className="h-8 animate-pulse rounded-md bg-surface-100" />
          ))}
        </div>
      ) : sessions.length === 0 ? (
        <p className="px-3 py-2 text-sm text-slate-400">No conversations yet.</p>
      ) : (
        <nav className="space-y-0.5">
          {sessions.map((s) => {
          const isActive = s.id === activeSessionId;
          return (
            <div
              key={s.id}
              className={`group relative flex items-center rounded-md px-3 py-2 text-sm transition-colors ${
                isActive
                  ? "bg-brand-50 text-brand-700"
                  : "text-slate-600 hover:bg-surface-50"
              }`}
            >
              <button
                onClick={() => onSelect(s.id)}
                className="min-w-0 flex-1 truncate text-left"
                title={s.title}
              >
                {s.title || "Untitled"}
              </button>

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(s.id);
                }}
                className={`ml-2 shrink-0 rounded p-0.5 transition-colors ${
                  confirmId === s.id
                    ? "text-red-500"
                    : "text-slate-300 opacity-0 group-hover:opacity-100 hover:text-red-500"
                }`}
                title={confirmId === s.id ? "Click again to delete" : "Delete"}
              >
                {confirmId === s.id ? (
                  <span className="text-xs font-semibold">Delete?</span>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                )}
              </button>
            </div>
          );
        })}
        </nav>
      )}
    </div>
  );
}
