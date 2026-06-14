/**
 * Typed client for the open-swe dashboard backend.
 *
 * All requests are sent with credentials so the httpOnly `osw_session`
 * cookie set by the OAuth callback rides along on cross-origin calls.
 */

const API_BASE = (import.meta.env.VITE_DASHBOARD_API_BASE_URL ?? "").replace(/\/$/, "");

if (!API_BASE && typeof window !== "undefined") {
  console.warn("VITE_DASHBOARD_API_BASE_URL is not set");
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export function isGithubReauthError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  if (error.status === 401) return true;
  return /github token|re-login required/i.test(error.message);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}/dashboard/api${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface SessionUser {
  login: string;
  actor_id?: string;
  auth_provider?: string;
  email: string | null;
  name?: string | null;
  tenant_id?: string | null;
  avatar_url: string | null;
  is_admin: boolean;
  slack_oauth_enabled?: boolean;
}

export interface ModelOption {
  id: string;
  label: string;
  efforts: Array<string>;
  default_effort: string;
  supports_images: boolean;
}

export interface OptionsPayload {
  models: Array<ModelOption>;
  default_agent_model: string;
  default_agent_reasoning_effort: string;
  default_agent_subagent_model: string;
  default_agent_subagent_reasoning_effort: string;
}

export interface Profile {
  login?: string;
  email?: string;
  default_model?: string;
  reasoning_effort?: string;
  default_subagent_model?: string | null;
  subagent_reasoning_effort?: string | null;
  default_repo?: string | null;
  base_branch?: string | null;
  branch_prefix?: string | null;
  auto_fix_ci?: boolean;
  create_prs?: boolean;
  review_draft_prs?: boolean | null;
  updated_at?: string;
}

export interface ProfileUpdate {
  default_model: string;
  reasoning_effort: string;
  default_subagent_model?: string | null;
  subagent_reasoning_effort?: string | null;
  default_repo?: string | null;
  base_branch?: string | null;
  branch_prefix?: string | null;
  auto_fix_ci?: boolean;
  create_prs?: boolean;
  review_draft_prs?: boolean | null;
}

export type TriggerMode = "every_push" | "once_per_pr" | "manual";
export type AutofixMode = "off" | "low" | "medium" | "high";

export interface TeamSettings {
  trigger_mode: TriggerMode;
  review_draft_prs: boolean;
  pr_summaries: boolean;
  review_trace_links: boolean;
  autofix_mode: AutofixMode;
  autofix_severity_threshold: AutofixMode;
  org_guidelines?: string | null;
  default_agent_model?: string | null;
  default_agent_reasoning_effort?: string | null;
  default_agent_subagent_model?: string | null;
  default_agent_subagent_reasoning_effort?: string | null;
  default_repo?: string | null;
  default_reviewer_model?: string | null;
  default_reviewer_reasoning_effort?: string | null;
  default_reviewer_subagent_model?: string | null;
  default_reviewer_subagent_reasoning_effort?: string | null;
  updated_at?: string | null;
}

export interface ProviderCredentialStatus {
  connected: boolean;
  site?: string;
  endpoint?: string;
  api_key_last4?: string;
  updated_at?: string | null;
}

export interface TeamCredentialsStatus {
  datadog: ProviderCredentialStatus;
  langsmith: ProviderCredentialStatus;
}

export interface DatadogConnectBody {
  site: string;
  api_key: string;
  app_key: string;
}

export interface LangSmithConnectBody {
  api_key: string;
  endpoint?: string | null;
}

export type AzureUsagePeriod = "7d" | "30d" | "all";

export interface AzureUsageCounterRow {
  name: string;
  count: number;
}

export interface AzureWorkItemMetrics {
  total: number;
  states: Array<AzureUsageCounterRow>;
  types: Array<AzureUsageCounterRow>;
  limited: boolean;
}

export interface AzureBuild {
  id: number;
  build_number: string | null;
  definition: string | null;
  status: string | null;
  result: string | null;
  source_branch: string | null;
  requested_for: string | null;
  queue_time: string | null;
  start_time: string | null;
  finish_time: string | null;
  web_url: string | null;
}

export interface AzureUsagePayload {
  project: string;
  period: AzureUsagePeriod;
  work_items: AzureWorkItemMetrics;
  recent_builds: Array<AzureBuild>;
}

export interface Workspace {
  id: string;
  label: string;
  path: string;
  current_branch: string | null;
  remote_url: string | null;
  is_dirty: boolean;
  azure_project?: string | null;
  azure_repo?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface WorkspacesPayload {
  workspaces: Array<Workspace>;
}

export interface WorkspaceCreate {
  path: string;
  label?: string | null;
  azure_project?: string | null;
  azure_repo?: string | null;
}

export interface Repository {
  /** Azure DevOps "<project>/<repo>" — the analogue of GitHub's owner/repo. */
  full_name: string;
  project?: string;
  name?: string;
  id?: string;
  default_branch?: string | null;
  web_url?: string | null;
  /** Legacy GitHub field, retained optional until the review pages are reworked. */
  private?: boolean;
}

export interface AzureProject {
  id: string;
  name: string;
  description?: string | null;
  state?: string | null;
}

export interface AzurePullRequest {
  id: number;
  title: string;
  status: string;
  is_draft: boolean;
  author: string | null;
  author_email: string | null;
  created_date: string | null;
  source_branch: string | null;
  target_branch: string | null;
  repo: string | null;
  project: string;
  web_url: string | null;
}

export interface ReposPayload {
  repositories: Array<Repository>;
  /** Legacy GitHub field, retained optional until the review pages are reworked. */
  installations?: Array<unknown>;
}

export type ReviewStyleStatus = "idle" | "running" | "completed" | "failed";

export interface ReviewStyle {
  full_name: string;
  owner?: string;
  name?: string;
  status: ReviewStyleStatus;
  custom_prompt: string | null;
  analysis_summary: string | null;
  top_reviewers: Array<string>;
  prs_sampled: number;
  reviews_sampled: number;
  analysis_thread_id: string | null;
  analysis_run_id: string | null;
  error: string | null;
  created_by?: string;
  created_at?: string;
  updated_at?: string;
}

export interface AgentInstructions {
  full_name: string;
  owner?: string;
  name?: string;
  instructions: string;
  created_by?: string;
  created_at?: string;
  updated_at?: string;
}

export const api = {
  me: () => request<SessionUser>("/me"),
  options: () => request<OptionsPayload>("/options"),
  profile: () => request<Profile>("/profile"),
  saveProfile: (body: ProfileUpdate) =>
    request<Profile>("/profile", { method: "PUT", body: JSON.stringify(body) }),
  repos: (project?: string) =>
    request<ReposPayload>(
      `/azure/repos${project ? `?project=${encodeURIComponent(project)}` : ""}`,
    ),
  azureProjects: () => request<Array<AzureProject>>("/azure/projects"),
  azurePullRequests: (project: string) =>
    request<{ pull_requests: Array<AzurePullRequest> }>(
      `/azure/pull-requests?project=${encodeURIComponent(project)}`,
    ),
  azureUsage: (project: string, period: AzureUsagePeriod = "30d") =>
    request<AzureUsagePayload>(
      `/azure/usage?project=${encodeURIComponent(project)}&period=${encodeURIComponent(period)}`,
    ),
  workspaces: () => request<WorkspacesPayload>("/workspaces"),
  registerWorkspace: (body: WorkspaceCreate) =>
    request<Workspace>("/workspaces", { method: "POST", body: JSON.stringify(body) }),
  pickWorkspace: () => request<Workspace>("/workspaces/pick", { method: "POST" }),
  listReviewStyles: () => request<Array<ReviewStyle>>("/review-styles"),
  createReviewStyle: (full_name: string) =>
    request<ReviewStyle>("/review-styles", {
      method: "POST",
      body: JSON.stringify({ full_name }),
    }),
  getReviewStyle: (full_name: string) =>
    request<ReviewStyle>(`/review-styles/${encodeURIComponent(full_name)}`),
  saveReviewStylePrompt: (full_name: string, custom_prompt: string) =>
    request<ReviewStyle>(`/review-styles/${encodeURIComponent(full_name)}`, {
      method: "PUT",
      body: JSON.stringify({ custom_prompt }),
    }),
  analyzeReviewStyle: (full_name: string) =>
    request<ReviewStyle>(`/review-styles/${encodeURIComponent(full_name)}/analyze`, {
      method: "POST",
    }),
  cancelReviewStyle: (full_name: string) =>
    request<ReviewStyle>(`/review-styles/${encodeURIComponent(full_name)}/cancel`, {
      method: "POST",
    }),
  deleteReviewStyle: (full_name: string) =>
    request<void>(`/review-styles/${encodeURIComponent(full_name)}`, {
      method: "DELETE",
    }),
  listAgentInstructions: () => request<Array<AgentInstructions>>("/agent-instructions"),
  createAgentInstructions: (full_name: string) =>
    request<AgentInstructions>("/agent-instructions", {
      method: "POST",
      body: JSON.stringify({ full_name }),
    }),
  getAgentInstructions: (full_name: string) =>
    request<AgentInstructions>(`/agent-instructions/${encodeURIComponent(full_name)}`),
  saveAgentInstructions: (full_name: string, instructions: string) =>
    request<AgentInstructions>(`/agent-instructions/${encodeURIComponent(full_name)}`, {
      method: "PUT",
      body: JSON.stringify({ instructions }),
    }),
  deleteAgentInstructions: (full_name: string) =>
    request<void>(`/agent-instructions/${encodeURIComponent(full_name)}`, {
      method: "DELETE",
    }),
  getTeamSettings: () => request<TeamSettings>("/team-settings"),
  saveTeamSettings: (body: TeamSettings) =>
    request<TeamSettings>("/team-settings", { method: "PUT", body: JSON.stringify(body) }),
  getTeamCredentials: () => request<TeamCredentialsStatus>("/team-credentials"),
  connectDatadog: (body: DatadogConnectBody) =>
    request<TeamCredentialsStatus>("/team-credentials/datadog", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  disconnectDatadog: () =>
    request<TeamCredentialsStatus>("/team-credentials/datadog", { method: "DELETE" }),
  connectLangSmith: (body: LangSmithConnectBody) =>
    request<TeamCredentialsStatus>("/team-credentials/langsmith", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  disconnectLangSmith: () =>
    request<TeamCredentialsStatus>("/team-credentials/langsmith", { method: "DELETE" }),
  listEnabledReviewRepos: () =>
    request<{ repos: Array<string> }>("/enabled-review-repos"),
  setEnabledReviewRepo: (full_name: string, enabled: boolean) =>
    request<{ repos: Array<string> }>("/enabled-review-repos", {
      method: "PUT",
      body: JSON.stringify({ full_name, enabled }),
    }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
};

export function loginUrl(redirectTo?: string): string {
  const target = redirectTo ?? (typeof window !== "undefined" ? window.location.origin : "");
  const qs = target ? `?redirect_to=${encodeURIComponent(target)}` : "";
  return `${API_BASE}/dashboard/api/entra/login${qs}`;
}
