"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminOnly, PageHeader, useMe } from "@/components/AppShell";
import { api, ApiError, formatDate, type AuditEntry, type Role, type User } from "@/lib/api";

export default function SettingsPage() {
  return (
    <AdminOnly>
      <PageHeader title="Settings" subtitle="Users and roles. Triage rules and fix limits arrive in build step 9." />
      <UsersSection />
      <AuditSection />
    </AdminOnly>
  );
}

function UsersSection() {
  const me = useMe();
  const [users, setUsers] = useState<User[] | null>(null);
  const [login, setLogin] = useState("");
  const [role, setRole] = useState<Role>("developer");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<User[]>("/admin/users")
      .then(setUsers)
      .catch((e) => setMessage({ kind: "error", text: e.message }));
  }, []);

  useEffect(load, [load]);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const created = await api<User>("/admin/users", { method: "POST", body: { github_login: login, role } });
      setMessage({ kind: "ok", text: `Invited ${created.github_login}. They can now log in with GitHub.` });
      setLogin("");
      load();
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Invite failed" });
    } finally {
      setBusy(false);
    }
  }

  async function update(user: User, patch: Partial<Pick<User, "role" | "is_active">>) {
    setMessage(null);
    try {
      await api<User>(`/admin/users/${user.id}`, { method: "PATCH", body: patch });
      load();
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Update failed" });
    }
  }

  return (
    <section className="card mb-6">
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <h2 className="font-medium">Users &amp; roles</h2>
      </div>

      <form onSubmit={invite} className="flex flex-wrap items-end gap-2 border-b border-line px-5 py-4">
        <label className="flex-1 min-w-[200px]">
          <span className="label">GitHub username</span>
          <input className="input mt-1" value={login} onChange={(e) => setLogin(e.target.value)} placeholder="octocat" />
        </label>
        <label>
          <span className="label">Role</span>
          <select className="input mt-1 w-36" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="developer">Developer</option>
            <option value="admin">Admin</option>
          </select>
        </label>
        <button className="btn-primary" disabled={busy || !login.trim()}>
          Invite user
        </button>
      </form>

      {message && (
        <p
          role={message.kind === "error" ? "alert" : "status"}
          className={`mx-5 mt-4 rounded-md px-3 py-2 text-sm ${message.kind === "error" ? "bg-red-50 text-red-800" : "bg-accent-soft text-accent"}`}
        >
          {message.text}
        </p>
      )}

      <div className="overflow-x-auto px-5 py-4">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="label border-b border-line">
              <th className="py-2 pr-4 font-medium">User</th>
              <th className="py-2 pr-4 font-medium">Role</th>
              <th className="py-2 pr-4 font-medium">Status</th>
              <th className="py-2 pr-4 font-medium">Last active</th>
              <th className="py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {users === null && (
              <tr>
                <td colSpan={5} className="py-4 text-ink-faint">
                  Loading…
                </td>
              </tr>
            )}
            {users?.map((u) => {
              const isMe = u.id === me.id;
              const status = !u.is_active ? "Deactivated" : u.last_login_at ? "Active" : "Invited";
              return (
                <tr key={u.id} className="border-b border-line last:border-0">
                  <td className="py-2.5 pr-4">
                    <span className="font-medium">{u.github_login}</span>
                    {u.name && <span className="ml-2 text-ink-faint">{u.name}</span>}
                    {isMe && <span className="ml-2 text-xs text-ink-faint">(you)</span>}
                  </td>
                  <td className="py-2.5 pr-4">
                    <select
                      className="input w-32 py-1"
                      value={u.role}
                      onChange={(e) => update(u, { role: e.target.value as Role })}
                      aria-label={`Role for ${u.github_login}`}
                    >
                      <option value="developer">Developer</option>
                      <option value="admin">Admin</option>
                    </select>
                  </td>
                  <td className="py-2.5 pr-4">
                    <span
                      className={`rounded px-1.5 py-0.5 text-xs ${
                        status === "Active" ? "bg-accent-soft text-accent" : status === "Invited" ? "bg-amber-50 text-amber-800" : "bg-canvas text-ink-faint"
                      }`}
                    >
                      {status}
                    </span>
                  </td>
                  <td className="py-2.5 pr-4 text-ink-soft">{formatDate(u.last_login_at)}</td>
                  <td className="py-2.5 text-right">
                    <button
                      className="btn-secondary px-2.5 py-1 text-xs"
                      onClick={() => update(u, { is_active: !u.is_active })}
                    >
                      {u.is_active ? "Deactivate" : "Reactivate"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function AuditSection() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);

  useEffect(() => {
    api<AuditEntry[]>("/admin/audit?limit=50").then(setEntries).catch(() => setEntries([]));
  }, []);

  return (
    <section className="card">
      <div className="border-b border-line px-5 py-3">
        <h2 className="font-medium">Audit log</h2>
        <p className="text-xs text-ink-faint">Latest 50 events: logins, invites and role changes.</p>
      </div>
      <div className="overflow-x-auto px-5 py-4">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="label border-b border-line">
              <th className="py-2 pr-4 font-medium">When</th>
              <th className="py-2 pr-4 font-medium">Who</th>
              <th className="py-2 pr-4 font-medium">Event</th>
              <th className="py-2 font-medium">Details</th>
            </tr>
          </thead>
          <tbody>
            {entries?.length === 0 && (
              <tr>
                <td colSpan={4} className="py-4 text-ink-faint">
                  No events yet.
                </td>
              </tr>
            )}
            {entries?.map((e) => (
              <tr key={e.id} className="border-b border-line align-top last:border-0">
                <td className="whitespace-nowrap py-2 pr-4 text-ink-soft">{formatDate(e.created_at)}</td>
                <td className="py-2 pr-4">{e.actor_label ?? "—"}</td>
                <td className="py-2 pr-4 font-mono text-xs">{e.action}</td>
                <td className="py-2 font-mono text-xs text-ink-soft">{describe(e.details)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function describe(details: Record<string, unknown>): string {
  return Object.entries(details)
    .map(([k, v]) => {
      if (v && typeof v === "object" && "from" in v && "to" in v) {
        const change = v as { from: unknown; to: unknown };
        return `${k}: ${String(change.from)} → ${String(change.to)}`;
      }
      return `${k}: ${String(v)}`;
    })
    .join(", ");
}
