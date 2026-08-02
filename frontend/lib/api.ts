const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3001";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("askit_token");
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem("askit_token", token);
  else localStorage.removeItem("askit_token");
}

export function getSessionId(): string {
  if (typeof window === "undefined") return "";
  let s = localStorage.getItem("askit_session");
  if (!s) {
    s = crypto.randomUUID();
    localStorage.setItem("askit_session", s);
  }
  return s;
}

export function setSessionId(id: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem("askit_session", id);
}

export function clearSessionId() {
  if (typeof window === "undefined") return;
  localStorage.removeItem("askit_session");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (init.body && !(init.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (res.status === 401) {
    setToken(null);
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, "Unauthorized");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || JSON.stringify(j);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  postForm: <T>(path: string, form: FormData) =>
    request<T>(path, { method: "POST", body: form }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

// ---------- SSE streaming ----------

export interface StreamEvent {
  event: string;
  session_id?: string;
  token?: string;
  answer?: string;
  queries?: string[];
  context?: string[];
}

export function askStream(
  query: string,
  sessionId: string,
  onEvent: (evt: StreamEvent) => void,
  onError: (err: Error) => void,
  onDone: () => void
): AbortController {
  const token = getToken();
  const ac = new AbortController();

  fetch(`${BASE}/ask/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ query, session_id: sessionId }),
    signal: ac.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        let detail = res.statusText;
        try {
          const j = await res.json();
          detail = j.detail || JSON.stringify(j);
        } catch {
          /* ignore */
        }
        throw new ApiError(res.status, detail);
      }
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || ""; // keep incomplete line

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              onEvent(data);
            } catch {
              /* bad JSON — skip */
            }
          }
        }
      }
      onDone();
    })
    .catch((err) => {
      if (err.name !== "AbortError") onError(err);
    });

  return ac;
}

// ---------- types ----------

export interface User {
  id: string;
  name: string;
  email: string;
}
export interface AuthResponse {
  token: string;
  user: User;
}
export interface EvalResults {
  created_at: string;
  metrics: Record<string, number>;
}
export interface JobStatus {
  job_id: string;
  state: string | null;
  user_id: string | null;
  attempts: number | null;
  num_chunks: number | null;
  error: string | null;
  file_path: string | null;
  sha256: string | null;
  created_at: string | null;
  updated_at: string | null;
}
export interface AskResponse {
  answer: string;
  session_id: string;
  queries: string[];
  keywords: string[];
  context: string[];
  num_candidates: number;
}
export interface PresignOut {
  upload_url: string;
  file_key: string;
}
export interface ChatSession {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}
export interface ChatMessage {
  id: number;
  session_id: string;
  role: "human" | "ai";
  content: string;
  context: string;
  queries: string;
  keywords: string;
  created_at: string;
}

export async function getSessions(): Promise<ChatSession[]> {
  return api.get<ChatSession[]>("/chat/sessions");
}

export async function getMessages(sessionId: string): Promise<ChatMessage[]> {
  return api.get<ChatMessage[]>(`/chat/session/${sessionId}/messages`);
}

export async function deleteSession(sessionId: string): Promise<void> {
  await api.del(`/chat/session/${sessionId}`);
}
