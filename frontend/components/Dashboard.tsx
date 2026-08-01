"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import EvalPanel from "./EvalPanel";
import DocumentsPanel from "./DocumentsPanel";
import AskPanel from "./AskPanel";

type Tab = "experiment" | "documents" | "ask";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "experiment", label: "Experiment", icon: "📊" },
  { id: "documents", label: "Documents", icon: "📄" },
  { id: "ask", label: "Ask", icon: "💬" },
];

export default function Dashboard() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("experiment");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-brand-600" />
      </main>
    );
  }

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-white p-5 sm:flex">
        <div className="mb-8 flex items-center gap-2">
          <div className="h-8 w-8 rounded-xl bg-gradient-to-br from-brand-500 to-indigo-500 shadow-glow" />
          <span className="text-lg font-bold tracking-tight">Askit</span>
        </div>

        <nav className="flex-1 space-y-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${
                tab === t.id
                  ? "bg-brand-50 text-brand-700"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              <span className="text-base">{t.icon}</span>
              {t.label}
            </button>
          ))}
        </nav>

        <div className="mt-4 border-t border-slate-100 pt-4">
          <div className="mb-3 truncate text-sm">
            <p className="truncate font-medium text-slate-800">{user.name}</p>
            <p className="truncate text-xs text-slate-400">{user.email}</p>
          </div>
          <button onClick={logout} className="btn-ghost w-full">Sign out</button>
        </div>
      </aside>

      {/* Mobile tab bar */}
      <div className="fixed bottom-0 left-0 right-0 z-10 flex border-t border-slate-200 bg-white sm:hidden">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex flex-1 flex-col items-center py-2 text-xs ${
              tab === t.id ? "text-brand-600" : "text-slate-500"
            }`}
          >
            <span className="text-lg">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      <main className="flex-1 overflow-y-auto p-6 pb-20 sm:pb-6 sm:p-8">
        <div className="mx-auto max-w-5xl">
          {tab === "experiment" && <EvalPanel />}
          {tab === "documents" && <DocumentsPanel />}
          {tab === "ask" && (
            <div className="h-[calc(100vh-7rem)] sm:h-[calc(100vh-5rem)]">
              <AskPanel />
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
