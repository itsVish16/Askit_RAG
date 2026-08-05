"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { useAuth } from "@/lib/auth";
import { getSessionId, setSessionId } from "@/lib/api";
import EvalPanel from "./EvalPanel";
import DocumentsPanel from "./DocumentsPanel";
import AskPanel from "./AskPanel";
import ChatHistory from "./ChatHistory";

type Tab = "experiment" | "documents" | "ask";

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  {
    id: "experiment",
    label: "Experiment",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-4 0v-5" />
        <path d="M12 12h.01" />
        <path d="M2 14h4" />
        <path d="M8 6h8" />
        <path d="M8 10h4" />
        <path d="M8 14h8" />
        <path d="M10 18h4" />
      </svg>
    ),
  },
  {
    id: "documents",
    label: "Documents",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
        <polyline points="10 9 9 9 8 9" />
      </svg>
    ),
  },
  {
    id: "ask",
    label: "Ask",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        <line x1="9" y1="10" x2="15" y2="10" />
        <line x1="12" y1="7" x2="12" y2="13" />
      </svg>
    ),
  },
];

export default function Dashboard() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("experiment");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sessionRefreshKey, setSessionRefreshKey] = useState(0);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  // Refresh chat history when AskPanel dispatches a session-updated event.
  useEffect(() => {
    const handler = () => {
      console.log(`[Dashboard] Received askit:session-updated! Incrementing sessionRefreshKey.`);
      setSessionRefreshKey((k) => k + 1);
    };
    window.addEventListener("askit:session-updated", handler);
    return () => window.removeEventListener("askit:session-updated", handler);
  }, []);

  // Session switching: when a chat history item is clicked.
  const handleSessionSelect = useCallback(
    (sessionId: string) => {
      setSessionId(sessionId);
      // Switch to the Ask tab to show the chat
      setTab("ask");
      setSidebarOpen(false); // Close mobile sidebar if open
      // Bump refresh key so AskPanel re-reads turns from server.
      setSessionRefreshKey((k) => k + 1);
    },
    []
  );

  if (loading || !user) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-3">
            <Image
              src="/logo-small.png"
              alt="Askit"
              width={40}
              height={40}
              className="h-10 w-auto object-contain transition-transform duration-300 group-hover:scale-110"
              priority
            />
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-zinc-300 border-t-brand-900" />
        </div>
      </main>
    );
  }

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-zinc-200 bg-surface-50 sm:flex">
        <div className="flex items-center gap-3 border-b border-zinc-200 px-5 py-4">
          <Image
            src="/logo.png"
            alt="Askit"
            width={120}
            height={40}
            className="h-8 w-auto shrink-0 object-contain"
          />
        </div>

        <nav className="space-y-0.5 p-3">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                tab === t.id
                  ? "bg-white text-zinc-900 shadow-sm border border-zinc-200/60 font-medium"
                  : "text-zinc-600 hover:bg-zinc-200/50"
              }`}
            >
              <span
                className={tab === t.id ? "text-brand-900" : "text-zinc-400"}
              >
                {t.icon}
              </span>
              {t.label}
            </button>
          ))}
        </nav>

        {/* Chat history — always visible so users can see conversations from any tab */}
        <ChatHistory
          activeSessionId={getSessionId()}
          onSelect={handleSessionSelect}
          refreshKey={sessionRefreshKey}
        />

        <div className="mt-auto border-t border-surface-100 p-3">
          <div className="mb-2 truncate px-1 text-sm">
            <p className="truncate font-medium text-zinc-900">{user.name}</p>
            <p className="truncate text-xs text-zinc-400">{user.email}</p>
          </div>
          <button onClick={logout} className="btn-ghost w-full justify-start text-xs">
            Sign out
          </button>
        </div>
      </aside>

      {/* Mobile header + sidebar overlay */}
      <div className="fixed top-0 left-0 right-0 z-20 flex items-center gap-3 border-b border-zinc-200 bg-white px-4 py-3 sm:hidden">
        <button onClick={() => setSidebarOpen(true)} className="text-zinc-600">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
        <Image src="/logo.png" alt="Askit" width={90} height={30} className="h-6 w-auto object-contain" />
      </div>

      {sidebarOpen && (
        <div className="fixed inset-0 z-30 sm:hidden">
          <div className="absolute inset-0 bg-black/20" onClick={() => setSidebarOpen(false)} />
          <aside className="relative flex h-full w-56 flex-col bg-surface-50 shadow-elevated">
            <div className="flex items-center justify-between border-b border-surface-100 px-5 py-4">
              <Image src="/logo.png" alt="Askit" width={90} height={30} className="h-6 w-auto object-contain" />
              <button onClick={() => setSidebarOpen(false)} className="text-zinc-400">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            <nav className="flex-1 space-y-0.5 p-3">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  onClick={() => { setTab(t.id); setSidebarOpen(false); }}
                  className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                    tab === t.id
                      ? "bg-white text-zinc-900 shadow-sm border border-zinc-200/60 font-medium"
                      : "text-zinc-600 hover:bg-zinc-200/50"
                  }`}
                >
                  <span className={tab === t.id ? "text-brand-900" : "text-zinc-400"}>{t.icon}</span>
                  {t.label}
                </button>
              ))}
            </nav>
            <div className="border-t border-surface-100 p-3">
              <button onClick={() => { logout(); setSidebarOpen(false); }} className="btn-ghost w-full justify-start text-xs">
                Sign out
              </button>
            </div>
          </aside>
        </div>
      )}

      <main className="flex-1 overflow-y-auto pt-14 sm:pt-0">
        <div className="mx-auto max-w-5xl p-4 sm:p-8">
          {/* Always render AskPanel — hidden class preserves its state across tab switches */}
          <div className={tab === "ask" ? "h-[calc(100vh-6rem)] sm:h-[calc(100vh-4rem)]" : "hidden"}>
            <AskPanel key={sessionRefreshKey} />
          </div>
          {tab === "experiment" && <EvalPanel />}
          {tab === "documents" && <DocumentsPanel />}
        </div>
      </main>
    </div>
  );
}
