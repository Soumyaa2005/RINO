"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";

import { api, ApiError, type Me } from "@/lib/api";

const SessionContext = createContext<Me | null>(null);

export function useMe(): Me {
  const me = useContext(SessionContext);
  if (!me) throw new Error("useMe must be used inside AppShell");
  return me;
}

type NavItem = { href: string; label: string; adminOnly?: boolean };

const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/review", label: "Code Review" },
  { href: "/testing", label: "Testing" },
  { href: "/performance", label: "Performance" },
  { href: "/repositories", label: "Repository Setup", adminOnly: true },
  { href: "/settings", label: "Settings", adminOnly: true },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    api<Me>("/auth/me")
      .then(setMe)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/login");
        else setLoadError(err instanceof Error ? err.message : "Could not load your session");
      });
  }, [router]);

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/login");
  }

  if (loadError) {
    return <p className="p-10 text-sm text-red-700">{loadError}</p>;
  }
  if (!me) {
    return <p className="p-10 text-sm text-ink-faint">Loading…</p>;
  }

  const isAdmin = me.role === "admin";
  const items = NAV.filter((item) => isAdmin || !item.adminOnly);
  const mainItems = items.filter((i) => !i.adminOnly);
  const adminItems = items.filter((i) => i.adminOnly);

  return (
    <SessionContext.Provider value={me}>
      <div className="flex min-h-screen">
        <aside className="flex w-56 shrink-0 flex-col border-r border-line bg-white">
          <div className="flex h-14 items-center gap-2 border-b border-line px-5">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-ink text-sm font-semibold text-white">R</span>
            <span className="font-semibold tracking-tight">Rino</span>
          </div>
          <nav className="flex-1 px-3 py-4 text-sm">
            <NavGroup items={mainItems} pathname={pathname} />
            {adminItems.length > 0 && (
              <>
                <p className="label mb-1 mt-6 px-2">Admin</p>
                <NavGroup items={adminItems} pathname={pathname} />
              </>
            )}
          </nav>
          <p className="border-t border-line px-5 py-3 text-xs text-ink-faint">{me.org_name}</p>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 items-center justify-between border-b border-line bg-white px-6">
            <div className="flex items-center gap-2 text-sm">
              <select className="input w-56 py-1.5" disabled aria-label="Repository">
                <option>No repositories yet</option>
              </select>
              <select className="input w-36 py-1.5" disabled aria-label="Branch">
                <option>Branch</option>
              </select>
            </div>
            <div className="flex items-center gap-3">
              {me.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={me.avatar_url} alt="" className="h-7 w-7 rounded-full" />
              ) : (
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-canvas text-xs font-medium">
                  {me.github_login.slice(0, 1).toUpperCase()}
                </span>
              )}
              <span className="text-sm">{me.name ?? me.github_login}</span>
              <RoleBadge role={me.role} />
              <button onClick={logout} className="btn-secondary px-2.5 py-1 text-xs">
                Log out
              </button>
            </div>
          </header>
          <main className="flex-1 p-6">{children}</main>
        </div>
      </div>
    </SessionContext.Provider>
  );
}

function NavGroup({ items, pathname }: { items: NavItem[]; pathname: string }) {
  return (
    <ul className="space-y-0.5">
      {items.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              className={`block rounded-md px-2 py-1.5 ${active ? "bg-canvas font-medium text-ink" : "text-ink-soft hover:bg-canvas"}`}
            >
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export function RoleBadge({ role }: { role: Me["role"] }) {
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide ${
        role === "admin" ? "bg-accent-soft text-accent" : "bg-canvas text-ink-soft"
      }`}
    >
      {role}
    </span>
  );
}

export function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      {subtitle && <p className="mt-1 text-sm text-ink-soft">{subtitle}</p>}
    </div>
  );
}

export function NotBuiltYet({ title, step, what }: { title: string; step: number; what: string }) {
  return (
    <>
      <PageHeader title={title} />
      <div className="card p-8 text-sm text-ink-soft">
        <p>{what}</p>
        <p className="mt-2 text-ink-faint">Arrives in build step {step}.</p>
      </div>
    </>
  );
}

export function AdminOnly({ children }: { children: React.ReactNode }) {
  const me = useMe();
  if (me.role !== "admin") {
    return <div className="card p-8 text-sm text-ink-soft">This page is for Admins only.</div>;
  }
  return <>{children}</>;
}
