export type Role = "admin" | "developer";

export interface User {
  id: string;
  github_login: string;
  name: string | null;
  avatar_url: string | null;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface Me extends User {
  org_name: string;
}

export interface AuditEntry {
  id: string;
  actor_label: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface AuthConfig {
  github_configured: boolean;
  dev_login: boolean;
}

export type RunnerType = "sandbox" | "github_actions" | "dev_instance";
export type ConfigStatus = "ready" | "needs_attention";

export interface TestConfig {
  runner: RunnerType;
  workflow_file: string | null;
  setup_command: string | null;
  test_command: string | null;
  python_version: string;
  shared_instance: boolean;
  status: ConfigStatus;
  problems: string[];
  warnings: string[];
  last_checked_at: string | null;
}

export interface Repo {
  id: string;
  full_name: string;
  default_branch: string;
  private: boolean;
  enabled: boolean;
  removed: boolean;
  installation_account: string;
  installation_usable: boolean;
  test_config: TestConfig | null;
}

export interface Installation {
  id: string;
  installation_id: number;
  account_login: string;
  account_type: string;
  suspended: boolean;
  removed: boolean;
  synced_at: string | null;
  repo_count: number;
}

export interface GithubStatus {
  app_configured: boolean;
  webhooks_configured: boolean;
  app_slug: string | null;
  installations: Installation[];
}

export const RUNNER_LABELS: Record<RunnerType, string> = {
  github_actions: "GitHub Actions",
  dev_instance: "Dev instance",
  sandbox: "Rino sandbox",
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: options.method ?? "GET",
    headers: { "Content-Type": "application/json", "X-Rino-CSRF": "1" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    credentials: "same-origin",
    cache: "no-store",
  });

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail) && data.detail[0]?.msg)
        message = String(data.detail[0].msg).replace(/^Value error, /, "");
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
