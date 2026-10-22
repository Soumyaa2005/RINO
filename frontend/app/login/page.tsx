"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { api, ApiError, type AuthConfig } from "@/lib/api";

const ERRORS: Record<string, string> = {
  no_access: "Your GitHub account doesn't have access to Rino yet. Ask your Admin to invite you.",
  invalid_state: "That sign-in link expired or was already used. Please try again.",
  github_failed: "GitHub sign-in didn't complete. Please try again.",
  github_cancelled: "GitHub sign-in was cancelled.",
  github_not_configured: "GitHub login isn't set up on this server yet. See the README.",
};

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [devLogin, setDevLogin] = useState("");
  const [devError, setDevError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const error = params.get("error");

  useEffect(() => {
    // Already signed in? Go straight to the app.
    api("/auth/me")
      .then(() => router.replace("/dashboard"))
      .catch(() => undefined);
    api<AuthConfig>("/auth/config").then(setConfig).catch(() => setConfig(null));
  }, [router]);

  async function submitDevLogin(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setDevError(null);
    try {
      await api("/auth/dev-login", { method: "POST", body: { github_login: devLogin } });
      router.replace("/dashboard");
    } catch (err) {
      setDevError(err instanceof ApiError ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-lg bg-ink text-lg font-semibold text-white">
            R
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Rino</h1>
          <p className="mt-2 text-sm text-ink-soft">
            Runs your repo&apos;s tests, triages the bugs, and suggests fixes you approve.
          </p>
        </div>

        <div className="card p-6">
          {error && (
            <p role="alert" className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
              {ERRORS[error] ?? "Sign-in failed. Please try again."}
            </p>
          )}

          <a
            href="/api/auth/github/login"
            className="btn-primary w-full py-2.5"
            aria-disabled={config ? !config.github_configured : undefined}
          >
            <GithubMark />
            Login with GitHub
          </a>
          <p className="mt-3 text-center text-xs text-ink-faint">Access is granted by your Admin.</p>

          {config?.dev_login && (
            <form onSubmit={submitDevLogin} className="mt-6 border-t border-dashed border-line pt-5">
              <p className="label mb-2">Dev login (local only)</p>
              <div className="flex gap-2">
                <input
                  className="input"
                  placeholder="GitHub username"
                  value={devLogin}
                  onChange={(e) => setDevLogin(e.target.value)}
                  aria-label="GitHub username for dev login"
                />
                <button className="btn-secondary" disabled={busy || !devLogin.trim()}>
                  Sign in
                </button>
              </div>
              {devError && <p className="mt-2 text-xs text-red-700">{devError}</p>}
            </form>
          )}
        </div>
      </div>
    </main>
  );
}

function GithubMark() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
