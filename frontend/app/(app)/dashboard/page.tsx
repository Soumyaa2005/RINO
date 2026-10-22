"use client";

import Link from "next/link";

import { PageHeader, useMe } from "@/components/AppShell";
import { useRepoSelection } from "@/components/RepoSelection";
import { RUNNER_LABELS } from "@/lib/api";

const CARDS = ["Critical", "High", "Medium", "Low", "Tests failed", "Fixes awaiting approval"];

export default function DashboardPage() {
  const me = useMe();
  const { repos, repo, branch, branchError } = useRepoSelection();
  const cfg = repo?.test_config ?? null;
  const ready = cfg?.status === "ready";

  return (
    <>
      <PageHeader title="Repository Dashboard" subtitle={repo ? `${repo.full_name} · ${branch ?? "…"}` : undefined} />

      {repos !== null && repos.length === 0 ? (
        <div className="card p-8 text-center text-sm text-ink-soft">
          <p className="font-medium text-ink">No repository connected yet</p>
          {me.role === "admin" ? (
            <p className="mt-1">
              Connect one from{" "}
              <Link href="/repositories" className="text-accent underline underline-offset-2">
                Repository Setup
              </Link>
              .
            </p>
          ) : (
            <p className="mt-1">An Admin needs to connect a repository before you can run an analysis.</p>
          )}
        </div>
      ) : (
        <>
          <div className="card mb-6 flex flex-wrap items-center justify-between gap-4 px-5 py-4">
            <div className="text-sm">
              <p className="label">Test environment</p>
              {cfg ? (
                <p className="mt-1">
                  {RUNNER_LABELS[cfg.runner]}
                  {cfg.runner !== "sandbox" && cfg.workflow_file && <span className="ml-2 font-mono text-xs text-ink-faint">{cfg.workflow_file}</span>}
                  {!ready && <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-xs font-medium text-amber-900">Needs attention</span>}
                </p>
              ) : (
                <p className="mt-1 text-ink-soft">Not set up</p>
              )}
              {branchError && <p className="mt-1 text-xs text-red-700">{branchError}</p>}
            </div>
            <div className="text-right">
              <button className="btn-primary" disabled title="Running an analysis arrives in build step 3">
                Start Analysis
              </button>
              <p className="mt-1 text-xs text-ink-faint">
                {!cfg || !ready
                  ? me.role === "admin"
                    ? "Finish this repo's test environment in Repository Setup first."
                    : "An Admin needs to finish this repo's test environment first."
                  : "Running an analysis arrives in build step 3."}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {CARDS.map((label) => (
              <div key={label} className="card px-4 py-3">
                <p className="label">{label}</p>
                <p className="mt-1 text-2xl font-semibold text-ink-faint">—</p>
              </div>
            ))}
          </div>
          <div className="card mt-6 p-8 text-center text-sm text-ink-faint">No analysis runs yet.</div>
        </>
      )}
    </>
  );
}
