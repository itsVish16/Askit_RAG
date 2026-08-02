"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await login(email, password);
      router.push("/");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell>
      <div className="mb-6 text-center">
        <h1 className="text-xl font-semibold text-slate-800">Sign in</h1>
        <p className="mt-1 text-sm text-slate-500">Upload documents and ask questions.</p>
      </div>

      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="email">Email</label>
          <input id="email" type="email" required className="input" value={email}
            onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </div>
        <div>
          <label className="label" htmlFor="password">Password</label>
          <input id="password" type="password" required className="input" value={password}
            onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
        </div>

        {err && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-600">{err}</p>}

        <button type="submit" disabled={busy} className="btn-primary w-full">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p className="mt-6 text-center text-sm text-slate-500">
        No account?{" "}
        <Link href="/register" className="font-medium text-brand-600 hover:text-brand-700">
          Create one
        </Link>
      </p>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-surface-50 p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3">
          <Image src="/logo.png" alt="Askit" width={64} height={43} priority />
          <span className="text-lg font-semibold text-slate-700">Askit</span>
        </div>
        <div className="card p-6">{children}</div>
      </div>
    </main>
  );
}
