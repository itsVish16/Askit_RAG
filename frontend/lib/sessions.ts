/** Session management — thin wrappers around the chat API for backward compat.
 *  The real work is in api.ts (getSessions, getMessages, deleteSession).
 *  This module re-exports and adds localStorage fallback for offline mode. */

import {
  ChatSession,
  getSessions as apiGetSessions,
  getMessages as apiGetMessages,
  deleteSession as apiDeleteSession,
  getSessionId,
  setSessionId,
} from "./api";

/** Get all sessions from the server, falling back to localStorage. */
export async function getSessions(): Promise<ChatSession[]> {
  try {
    return await apiGetSessions();
  } catch {
    return localGetSessions();
  }
}

/** Get messages for a session from the server, falling back to localStorage. */
export async function getMessages(
  sessionId: string
): Promise<{ role: string; content: string }[]> {
  try {
    const msgs = await apiGetMessages(sessionId);
    return msgs.map((m) => ({ role: m.role, content: m.content }));
  } catch {
    return localGetMessages(sessionId);
  }
}

/** Delete a session from the server and localStorage. */
export async function removeSession(sessionId: string): Promise<void> {
  try {
    await apiDeleteSession(sessionId);
  } catch {
    /* server may not have it */
  }
  localRemove(sessionId);
}

/** Start a new conversation (new session_id, clear local cache). */
export function newConversation(): string {
  const newId = crypto.randomUUID();
  setSessionId(newId);
  return newId;
}

// ---------- localStorage fallback ----------

const SESSION_KEY = "askit_sessions";
const TURNS_PREFIX = "askit_turns_";

function localGetSessions(): ChatSession[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY) || "[]");
  } catch {
    return [];
  }
}

function localGetMessages(sessionId: string) {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(TURNS_PREFIX + sessionId) || "[]");
  } catch {
    return [];
  }
}

function localRemove(sessionId: string) {
  if (typeof window === "undefined") return;
  const sessions = localGetSessions().filter((s) => s.id !== sessionId);
  localStorage.setItem(SESSION_KEY, JSON.stringify(sessions));
  localStorage.removeItem(TURNS_PREFIX + sessionId);
}
