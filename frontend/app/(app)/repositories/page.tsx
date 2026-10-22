"use client";

import { AdminOnly, NotBuiltYet } from "@/components/AppShell";

export default function RepositoriesPage() {
  return (
    <AdminOnly>
      <NotBuiltYet
        title="Repository Setup"
        step={2}
        what="Install the GitHub App, pick repositories, and choose where each repo's tests run."
      />
    </AdminOnly>
  );
}
