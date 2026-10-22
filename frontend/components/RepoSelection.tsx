"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api, type Repo } from "@/lib/api";

interface RepoSelection {
  repos: Repo[] | null;
  repo: Repo | null;
  branches: string[] | null;
  branch: string | null;
  branchError: string | null;
  selectRepo: (id: string) => void;
  selectBranch: (name: string) => void;
  reload: () => void;
}

const Ctx = createContext<RepoSelection | null>(null);
const STORAGE_KEY = "rino.selection";

function readSaved(): { repoId?: string; branch?: string } {
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
  } catch {
    return {};
  }
}

function save(repoId: string | null, branch: string | null) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ repoId, branch }));
  } catch {
    /* storage unavailable: selection just won't be remembered */
  }
}

export function RepoSelectionProvider({ children }: { children: React.ReactNode }) {
  const [repos, setRepos] = useState<Repo[] | null>(null);
  const [repoId, setRepoId] = useState<string | null>(null);
  const [branches, setBranches] = useState<string[] | null>(null);
  const [branch, setBranch] = useState<string | null>(null);
  const [branchError, setBranchError] = useState<string | null>(null);

  const reload = useCallback(() => {
    api<Repo[]>("/repos")
      .then((list) => {
        setRepos(list);
        setRepoId((current) => {
          const wanted = current ?? readSaved().repoId;
          return list.some((r) => r.id === wanted) ? wanted! : (list[0]?.id ?? null);
        });
      })
      .catch(() => setRepos([]));
  }, []);

  useEffect(reload, [reload]);

  useEffect(() => {
    setBranches(null);
    setBranchError(null);
    if (!repoId) {
      setBranch(null);
      return;
    }
    let cancelled = false;
    api<string[]>(`/repos/${repoId}/branches`)
      .then((list) => {
        if (cancelled) return;
        setBranches(list);
        const saved = readSaved();
        setBranch(saved.repoId === repoId && saved.branch && list.includes(saved.branch) ? saved.branch : (list[0] ?? null));
      })
      .catch((err) => {
        if (cancelled) return;
        setBranches([]);
        setBranch(null);
        setBranchError(err instanceof Error ? err.message : "Couldn't load branches");
      });
    return () => {
      cancelled = true;
    };
  }, [repoId]);

  useEffect(() => {
    if (repoId && branch) save(repoId, branch);
  }, [repoId, branch]);

  const value: RepoSelection = {
    repos,
    repo: repos?.find((r) => r.id === repoId) ?? null,
    branches,
    branch,
    branchError,
    selectRepo: setRepoId,
    selectBranch: setBranch,
    reload,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useRepoSelection(): RepoSelection {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useRepoSelection must be used inside RepoSelectionProvider");
  return ctx;
}

export function RepoPicker() {
  const { repos, repo, branches, branch, selectRepo, selectBranch } = useRepoSelection();
  const empty = repos !== null && repos.length === 0;

  return (
    <div className="flex items-center gap-2 text-sm">
      <select
        className="input w-60 py-1.5"
        aria-label="Repository"
        disabled={!repos || empty}
        value={repo?.id ?? ""}
        onChange={(e) => selectRepo(e.target.value)}
      >
        {repos === null && <option value="">Loading…</option>}
        {empty && <option value="">No repositories yet</option>}
        {repos?.map((r) => (
          <option key={r.id} value={r.id}>
            {r.full_name}
            {r.test_config?.status !== "ready" ? " (not ready)" : ""}
          </option>
        ))}
      </select>
      <select
        className="input w-44 py-1.5"
        aria-label="Branch"
        disabled={!branches || branches.length === 0}
        value={branch ?? ""}
        onChange={(e) => selectBranch(e.target.value)}
      >
        {!repo && <option value="">Branch</option>}
        {repo && branches === null && <option value="">Loading…</option>}
        {branches?.map((b) => (
          <option key={b} value={b}>
            {b}
          </option>
        ))}
      </select>
    </div>
  );
}
