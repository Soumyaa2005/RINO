"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { AdminOnly, PageHeader } from "@/components/AppShell";
import { useRepoSelection } from "@/components/RepoSelection";
import {
  api,
  ApiError,
  formatDate,
  RUNNER_LABELS,
  type GithubStatus,
  type Repo,
  type RunnerType,
  type TestConfig,
} from "@/lib/api";

const BANNERS: Record<string, { kind: "ok" | "error"; text: string }> = {
  installed: { kind: "ok", text: "GitHub App connected. Repositories are synced below." },
  app_not_configured: { kind: "error", text: "The GitHub App isn't configured on this server yet. See the README." },
  invalid_state: { kind: "error", text: "That install link expired or didn't start from Rino. Click Install GitHub App again." },
  install_failed: { kind: "error", text: "Rino couldn't verify that installation with GitHub. Try installing again." },
  sync_failed: { kind: "error", text: "Connected, but syncing repositories failed. Use Sync repos to retry." },
  install_requested: { kind: "ok", text: "Install requested. An owner of the GitHub organization needs to approve it." },
  forbidden: { kind: "error", text: "Only Admins can connect GitHub." },
};

export default function RepositoriesPage() {
  return (
    <AdminOnly>
      <PageHeader title="Repository Setup" subtitle="Connect GitHub, choose repositories, and tell Rino where each repo's tests run." />
      <Suspense>
        <Banner />
      </Suspense>
      <Setup />
    </AdminOnly>
  );
}

function Banner() {
  const params = useSearchParams();
  const key = params.get("installed") ? "installed" : params.get("error");
  const banner = key ? BANNERS[key] : null;
  if (!banner) return null;
  return (
    <p
      role={banner.kind === "error" ? "alert" : "status"}
      className={`mb-4 rounded-md px-3 py-2 text-sm ${banner.kind === "error" ? "bg-red-50 text-red-800" : "bg-accent-soft text-accent"}`}
    >
      {banner.text}
    </p>
  );
}

function Setup() {
  const selection = useRepoSelection();
  const [status, setStatus] = useState<GithubStatus | null>(null);
  const [repos, setRepos] = useState<Repo[] | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<string | null>(null);

  const load = useCallback(() => {
    api<GithubStatus>("/admin/github/status").then(setStatus).catch((e) => setError(e.message));
    api<Repo[]>("/admin/repos").then(setRepos).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  function changed(updated?: Repo) {
    if (updated) setRepos((list) => list?.map((r) => (r.id === updated.id ? updated : r)) ?? null);
    else load();
    selection.reload();
  }

  async function sync(instId: string) {
    setSyncing(instId);
    setError(null);
    try {
      await api(`/admin/github/installations/${instId}/sync`, { method: "POST" });
      changed();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Sync failed");
    } finally {
      setSyncing(null);
    }
  }

  async function toggle(repo: Repo) {
    try {
      changed(await api<Repo>(`/admin/repos/${repo.id}`, { method: "PATCH", body: { enabled: !repo.enabled } }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Update failed");
    }
  }

  const active = repos?.filter((r) => !r.removed) ?? [];
  const removed = repos?.filter((r) => r.removed) ?? [];

  return (
    <>
      {error && (
        <p role="alert" className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </p>
      )}

      {/* ---- GitHub connection ---- */}
      <section className="card mb-6">
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <div>
            <h2 className="font-medium">GitHub connection</h2>
            <p className="text-xs text-ink-faint">Rino only sees the repositories you pick when installing the GitHub App.</p>
          </div>
          {status?.app_configured && (
            <a href="/api/admin/github/install" className="btn-primary">
              {status.installations.some((i) => !i.removed) ? "Add or change repositories" : "Install GitHub App"}
            </a>
          )}
        </div>
        <div className="px-5 py-4 text-sm">
          {status === null && <p className="text-ink-faint">Loading…</p>}
          {status && !status.app_configured && (
            <p className="text-ink-soft">
              The GitHub App isn&apos;t configured on this server. Set <code className="font-mono text-xs">GITHUB_APP_ID</code>,{" "}
              <code className="font-mono text-xs">GITHUB_APP_SLUG</code> and the private key in <code className="font-mono text-xs">.env</code> (see
              README), then restart.
            </p>
          )}
          {status?.app_configured && !status.webhooks_configured && (
            <p className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-amber-900">
              Webhooks aren&apos;t set up, so repo changes on GitHub won&apos;t show up automatically. Use <b>Sync repos</b>, or set{" "}
              <code className="font-mono text-xs">GITHUB_WEBHOOK_SECRET</code>.
            </p>
          )}
          {status?.app_configured && status.installations.length === 0 && (
            <p className="text-ink-soft">Not connected yet. Click Install GitHub App and choose which repositories Rino can access.</p>
          )}
          {status && status.installations.length > 0 && (
            <ul className="divide-y divide-line">
              {status.installations.map((i) => (
                <li key={i.id} className="flex items-center justify-between py-2.5">
                  <div>
                    <span className="font-medium">{i.account_login}</span>
                    <span className="ml-2 text-ink-faint">{i.account_type}</span>
                    {i.removed && <Badge tone="muted">Uninstalled</Badge>}
                    {i.suspended && <Badge tone="warn">Suspended</Badge>}
                    <p className="text-xs text-ink-faint">
                      {i.repo_count} {i.repo_count === 1 ? "repository" : "repositories"} · last synced {formatDate(i.synced_at)}
                    </p>
                  </div>
                  {!i.removed && (
                    <button className="btn-secondary px-2.5 py-1 text-xs" disabled={syncing === i.id} onClick={() => sync(i.id)}>
                      {syncing === i.id ? "Syncing…" : "Sync repos"}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* ---- Repositories ---- */}
      <section className="card">
        <div className="border-b border-line px-5 py-3">
          <h2 className="font-medium">Repositories</h2>
          <p className="text-xs text-ink-faint">Developers see enabled repositories. Analysis needs a test environment marked Ready.</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="label border-b border-line">
                <th className="px-5 py-2 font-medium">Repository</th>
                <th className="px-3 py-2 font-medium">Default branch</th>
                <th className="px-3 py-2 font-medium">Tests run in</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Visible to developers</th>
                <th className="px-5 py-2" />
              </tr>
            </thead>
            <tbody>
              {repos === null && (
                <tr>
                  <td colSpan={6} className="px-5 py-4 text-ink-faint">
                    Loading…
                  </td>
                </tr>
              )}
              {repos !== null && active.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-4 text-ink-faint">
                    No repositories yet.
                  </td>
                </tr>
              )}
              {active.map((repo) => (
                <RepoRow
                  key={repo.id}
                  repo={repo}
                  open={editing === repo.id}
                  onToggleOpen={() => setEditing(editing === repo.id ? null : repo.id)}
                  onToggleEnabled={() => toggle(repo)}
                  onSaved={changed}
                />
              ))}
            </tbody>
          </table>
        </div>
        {removed.length > 0 && (
          <p className="border-t border-line px-5 py-3 text-xs text-ink-faint">
            No longer shared with the GitHub App: {removed.map((r) => r.full_name).join(", ")}
          </p>
        )}
      </section>
    </>
  );
}

function RepoRow({
  repo,
  open,
  onToggleOpen,
  onToggleEnabled,
  onSaved,
}: {
  repo: Repo;
  open: boolean;
  onToggleOpen: () => void;
  onToggleEnabled: () => void;
  onSaved: (r: Repo) => void;
}) {
  const cfg = repo.test_config;
  return (
    <>
      <tr className="border-b border-line">
        <td className="px-5 py-2.5">
          <span className="font-medium">{repo.full_name}</span>
          {repo.private && <Badge tone="muted">Private</Badge>}
        </td>
        <td className="px-3 py-2.5 font-mono text-xs text-ink-soft">{repo.default_branch}</td>
        <td className="px-3 py-2.5 text-ink-soft">{cfg ? RUNNER_LABELS[cfg.runner] : "—"}</td>
        <td className="px-3 py-2.5">
          <StatusBadge config={cfg} />
        </td>
        <td className="px-3 py-2.5">
          <label className="inline-flex cursor-pointer items-center gap-2">
            <input type="checkbox" checked={repo.enabled} onChange={onToggleEnabled} className="h-4 w-4 accent-ink" />
            <span className="text-ink-soft">{repo.enabled ? "Yes" : "No"}</span>
          </label>
        </td>
        <td className="px-5 py-2.5 text-right">
          <button className="btn-secondary px-2.5 py-1 text-xs" onClick={onToggleOpen} aria-expanded={open}>
            {open ? "Close" : cfg ? "Edit" : "Set up"}
          </button>
        </td>
      </tr>
      {open && (
        <tr className="border-b border-line bg-canvas">
          <td colSpan={6} className="px-5 py-5">
            <TestEnvForm repo={repo} onSaved={onSaved} />
          </td>
        </tr>
      )}
    </>
  );
}

const RUNNER_OPTIONS: { value: RunnerType; title: string; body: string }[] = [
  { value: "github_actions", title: "GitHub Actions", body: "Rino starts your existing test workflow on GitHub and reads the results." },
  { value: "dev_instance", title: "Dev instance", body: "Same workflow, run on your own server through a GitHub self-hosted runner." },
  { value: "sandbox", title: "Rino sandbox", body: "Rino clones the repo into an isolated Docker container and runs pytest itself." },
];

const PYTHON_VERSIONS = ["3.9", "3.10", "3.11", "3.12", "3.13"];

function TestEnvForm({ repo, onSaved }: { repo: Repo; onSaved: (r: Repo) => void }) {
  const cfg = repo.test_config;
  const [runner, setRunner] = useState<RunnerType>(cfg?.runner ?? "github_actions");
  const [workflow, setWorkflow] = useState(cfg?.workflow_file ?? "");
  const [setupCmd, setSetupCmd] = useState(cfg?.setup_command ?? "pip install -r requirements.txt");
  const [testCmd, setTestCmd] = useState(cfg?.test_command ?? "pytest");
  const [python, setPython] = useState(cfg?.python_version ?? "3.11");
  const [shared, setShared] = useState(cfg?.shared_instance ?? false);
  const [workflows, setWorkflows] = useState<string[] | null>(null);
  const [busy, setBusy] = useState<"save" | "check" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const usesWorkflow = runner !== "sandbox";

  useEffect(() => {
    if (!usesWorkflow || workflows !== null) return;
    api<{ path: string }[]>(`/admin/repos/${repo.id}/workflows`)
      .then((list) => {
        const paths = list.map((w) => w.path);
        setWorkflows(paths);
        setWorkflow((current) => current || paths[0] || "");
      })
      .catch(() => setWorkflows([]));
  }, [usesWorkflow, workflows, repo.id]);

  async function saveAndCheck(e: React.FormEvent) {
    e.preventDefault();
    setBusy("save");
    setError(null);
    try {
      const body = usesWorkflow
        ? { runner, workflow_file: workflow, python_version: python, shared_instance: runner === "dev_instance" && shared }
        : { runner, setup_command: setupCmd, test_command: testCmd, python_version: python };
      onSaved(await api<Repo>(`/admin/repos/${repo.id}/test-config`, { method: "PUT", body }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Save failed");
    } finally {
      setBusy(null);
    }
  }

  async function recheck() {
    setBusy("check");
    setError(null);
    try {
      onSaved(await api<Repo>(`/admin/repos/${repo.id}/test-config/check`, { method: "POST" }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Check failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <form onSubmit={saveAndCheck} className="max-w-3xl">
      <p className="mb-2 text-sm font-medium">Where do your tests run?</p>
      <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Where tests run">
        {RUNNER_OPTIONS.map((opt) => (
          <label
            key={opt.value}
            className={`cursor-pointer rounded-lg border bg-white p-3 text-sm ${runner === opt.value ? "border-ink ring-1 ring-ink" : "border-line hover:border-ink-faint"}`}
          >
            <input type="radio" name={`runner-${repo.id}`} value={opt.value} checked={runner === opt.value} onChange={() => setRunner(opt.value)} className="sr-only" />
            <span className="block font-medium">{opt.title}</span>
            <span className="mt-1 block text-xs text-ink-soft">{opt.body}</span>
          </label>
        ))}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {usesWorkflow ? (
          <label className="sm:col-span-2">
            <span className="label">Workflow that runs your tests</span>
            {workflows && workflows.length > 0 ? (
              <select className="input mt-1 font-mono" value={workflow} onChange={(e) => setWorkflow(e.target.value)}>
                {!workflows.includes(workflow) && workflow && <option value={workflow}>{workflow}</option>}
                {workflows.map((w) => (
                  <option key={w} value={w}>
                    {w}
                  </option>
                ))}
              </select>
            ) : (
              <input className="input mt-1 font-mono" value={workflow} onChange={(e) => setWorkflow(e.target.value)} placeholder=".github/workflows/test.yml" />
            )}
            <span className="mt-1 block text-xs text-ink-faint">
              {workflows === null ? "Looking for workflow files…" : workflows.length === 0 ? `No workflow files found on ${repo.default_branch}; type the path.` : "Needs a workflow_dispatch trigger so Rino can start it."}
            </span>
          </label>
        ) : (
          <>
            <label className="sm:col-span-2">
              <span className="label">Setup command</span>
              <input className="input mt-1 font-mono" value={setupCmd} onChange={(e) => setSetupCmd(e.target.value)} />
            </label>
            <label>
              <span className="label">Test command</span>
              <input className="input mt-1 font-mono" value={testCmd} onChange={(e) => setTestCmd(e.target.value)} />
              <span className="mt-1 block text-xs text-ink-faint">One pytest command. Rino adds --junitxml itself.</span>
            </label>
            <label>
              <span className="label">Python version</span>
              <select className="input mt-1" value={python} onChange={(e) => setPython(e.target.value)}>
                {PYTHON_VERSIONS.map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
          </>
        )}
        {runner === "dev_instance" && (
          <label className="flex items-start gap-2 text-sm sm:col-span-2">
            <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} className="mt-0.5 h-4 w-4 accent-ink" />
            <span>
              Dev instance is shared with developers
              <span className="block text-xs text-ink-faint">Rino will run one job at a time so it doesn&apos;t clash with people&apos;s work.</span>
            </span>
          </label>
        )}
      </div>

      {error && (
        <p role="alert" className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </p>
      )}

      <div className="mt-4 flex items-center gap-2">
        <button className="btn-primary" disabled={busy !== null}>
          {busy === "save" ? "Saving…" : "Save & check"}
        </button>
        {cfg && (
          <button type="button" className="btn-secondary" disabled={busy !== null} onClick={recheck}>
            {busy === "check" ? "Checking…" : "Test connection"}
          </button>
        )}
      </div>

      {cfg && <CheckResults config={cfg} />}
    </form>
  );
}

function CheckResults({ config }: { config: TestConfig }) {
  return (
    <div className="mt-4 rounded-lg border border-line bg-white p-4 text-sm">
      <div className="flex items-center gap-2">
        <StatusBadge config={config} />
        <span className="text-xs text-ink-faint">Last checked {formatDate(config.last_checked_at)}</span>
      </div>
      {config.problems.length === 0 && config.warnings.length === 0 && <p className="mt-2 text-ink-soft">All checks passed.</p>}
      {config.problems.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {config.problems.map((p) => (
            <li key={p} className="flex gap-2 text-red-800">
              <span aria-hidden>✕</span>
              <span>{p}</span>
            </li>
          ))}
        </ul>
      )}
      {config.warnings.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {config.warnings.map((w) => (
            <li key={w} className="flex gap-2 text-amber-900">
              <span aria-hidden>!</span>
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StatusBadge({ config }: { config: TestConfig | null }) {
  if (!config) return <Badge tone="muted">Not set up</Badge>;
  return config.status === "ready" ? <Badge tone="ok">Ready</Badge> : <Badge tone="warn">Needs attention</Badge>;
}

function Badge({ tone, children }: { tone: "ok" | "warn" | "muted"; children: React.ReactNode }) {
  const styles = { ok: "bg-accent-soft text-accent", warn: "bg-amber-50 text-amber-900", muted: "bg-canvas text-ink-faint" }[tone];
  return <span className={`ml-2 inline-block rounded px-1.5 py-0.5 text-xs font-medium first:ml-0 ${styles}`}>{children}</span>;
}
