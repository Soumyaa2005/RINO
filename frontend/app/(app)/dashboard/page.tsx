"use client";

import Link from "next/link";

import { PageHeader, useMe } from "@/components/AppShell";

const CARDS = ["Critical", "High", "Medium", "Low", "Tests failed", "Fixes awaiting approval"];

export default function DashboardPage() {
  const me = useMe();
  return (
    <>
      <PageHeader title="Repository Dashboard" subtitle={`Signed in as ${me.github_login} (${me.role}).`} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {CARDS.map((label) => (
          <div key={label} className="card px-4 py-3">
            <p className="label">{label}</p>
            <p className="mt-1 text-2xl font-semibold text-ink-faint">—</p>
          </div>
        ))}
      </div>

      <div className="card mt-6 p-8 text-center text-sm text-ink-soft">
        <p className="font-medium text-ink">No repository connected yet</p>
        {me.role === "admin" ? (
          <p className="mt-1">
            Connect one from{" "}
            <Link href="/repositories" className="text-accent underline underline-offset-2">
              Repository Setup
            </Link>{" "}
            (arrives in build step 2).
          </p>
        ) : (
          <p className="mt-1">An Admin needs to connect a repository before you can run an analysis.</p>
        )}
      </div>
    </>
  );
}
