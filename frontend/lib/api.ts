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
};

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
