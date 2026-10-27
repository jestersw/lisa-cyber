export const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "lisa_operator_token";

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

let authToken: string | null = readStoredToken();

export function setToken(token: string | null): void {
  authToken = token;
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // Private mode / disabled storage: keep the in-memory token and carry on.
  }
}

export function getToken(): string | null {
  return authToken;
}

export function isAuthenticated(): boolean {
  return authToken !== null;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

interface RequestOptions {
  // When true, a 401 does NOT clear the operator session / redirect to login.
  // Used for agent-token-only endpoints the operator panel reads best-effort
  // (agent config, next-activity): the operator can't authenticate to them when
  // an agent token is enforced, and that must not look like an expired session.
  silent401?: boolean;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  opts: RequestOptions = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (authToken) {
    headers.set("Authorization", `Bearer ${authToken}`);
  }

  const response = await fetch(`${BASE_URL}${path}`, { ...init, headers });

  if (response.status === 401) {
    if (!opts.silent401) {
      setToken(null);
      // Let the app route back to the login screen (listener in App).
      if (typeof window !== "undefined") {
        window.dispatchEvent(new Event("lisa:auth-expired"));
      }
    }
    throw new ApiError(401, "Unauthorized");
  }
  if (!response.ok) {
    const detail = await response.text();
    throw new ApiError(response.status, detail || response.statusText);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>(path, {}, opts),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface Role {
  id: number;
  name: string;
  description: string | null;
  category: string | null;
  is_active: boolean;
  created_at?: string;
}

export interface BehaviorTemplate {
  id: number;
  name: string;
  description?: string | null;
  role_id: number | null;
  os_type: string;
  version?: string;
  is_active?: boolean;
  template_data: { applications_used?: string[]; [key: string]: unknown };
}

export interface ApplicationTemplate {
  id: number;
  name: string;
  display_name: string | null;
  category: string | null;
  description?: string | null;
  os_type: string;
  version?: string;
  author?: string | null;
  is_active?: boolean;
  template_config?: Record<string, unknown>;
}

export interface MlStatus {
  models_dir: string;
  shared_loaded: boolean;
  shared_states: number;
  [key: string]: unknown;
}

export interface Agent {
  id: number;
  agent_id: string;
  name: string;
  status: string;
  os_type: string;
  last_seen: string | null;
  created_at: string;
}

export interface GenerateAgentResponse {
  agent_id: string;
  message: string;
  config: { build_status?: string; [key: string]: unknown };
  config_url: string;
  status_url: string;
}

export interface Meta {
  os_types: string[];
  buildable_os: string[];
}

export interface FleetAgent {
  agent_id: string;
  name: string;
  role: string | null;
  os_type: string;
  status: string;
  current_app: string | null;
  last_seen: string | null;
}

export interface LiveEvent {
  id: number;
  agent_id: string | null;
  name: string | null;
  app: string;
  activity_type: string;
  role: string | null;
  duration_seconds: number | null;
  context: Record<string, unknown> | null;
  timestamp: string | null;
}

export interface LiveEventsResponse {
  events: LiveEvent[];
  latest_id: number | null;
}


export interface AgentStatus {
  agent: {
    agent_id: string;
    name: string;
    status: string;
    os_type: string;
    role: string | null;
    last_seen: string | null;
    binary_url: string | null;
    installer_url: string | null;
  };
  recent_activities: {
    id: number;
    type: string;
    data: Record<string, unknown> | null;
    timestamp: string;
  }[];
}

export interface HeartbeatLog {
  agent_id: string;
  status: string;
  last_seen: string | null;
  heartbeats: { timestamp: string; data: Record<string, unknown> | null }[];
}

export interface DeploymentPackage {
  agent_config: {
    agent_info: { agent_id: string; name: string; role: string; os_type: string };
    schedule: {
      workdays: number[];
      work_start: string;
      work_end: string;
      lunch: { earliest: string; latest: string; min_minutes: number; max_minutes: number };
    };
    behavior: Record<string, { min: number; max: number }>;
    heartbeat: { interval_minutes: number };
    applications: string[];
  };
  application_plugins: Record<string, unknown>;
}

export interface DeployTarget {
  host: string;
  ssh_user?: string | null;
  become?: boolean | null;
}

export interface DeployRequest {
  targets: DeployTarget[];
  backend_url?: string | null;
  force?: boolean;
}

export interface Deployment {
  id: number;
  agent_id: string;
  backend: string;
  status: string;
  returncode: number | null;
  output: string | null;
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
}

export interface DiagnosisFinding {
  issue: string;
  evidence?: string | null;
  severity: "info" | "warning" | "critical";
}

export interface DiagnosisChange {
  target: string;
  change: string;
}

export interface Diagnosis {
  agent_id: string;
  source: "model" | "unavailable";
  summary: string;
  findings: DiagnosisFinding[];
  suggested_changes: DiagnosisChange[];
  signals: Record<string, unknown>;
}

export interface NextActivity {
  agent_id: string;
  current: string | null;
  next_activity: string;
  activity_type: string;
  source: string;
  trained_on: string | null;
  distribution?: Record<string, number>;
}

export const endpoints = {
  login: async (password: string): Promise<TokenResponse> => {
    const token = await api.post<TokenResponse>("/api/auth/login", { password });
    setToken(token.access_token);
    return token;
  },
  logout: (): void => setToken(null),
  roles: () => api.get<Role[]>("/api/roles"),
  createRole: (body: { name: string; description?: string; category?: string }) =>
    api.post<Role>("/api/roles", body),
  updateRole: (id: number, body: Partial<Role>) => api.put<Role>(`/api/roles/${id}`, body),
  deleteRole: (id: number) => api.del<void>(`/api/roles/${id}`),
  behaviorTemplates: () => api.get<BehaviorTemplate[]>("/api/behavior-templates"),
  createBehaviorTemplate: (body: {
    name: string;
    description?: string;
    role_id: number;
    template_data: Record<string, unknown>;
    os_type: string;
  }) => api.post<BehaviorTemplate>("/api/behavior-templates", body),
  updateBehaviorTemplate: (id: number, body: Partial<BehaviorTemplate>) =>
    api.put<BehaviorTemplate>(`/api/behavior-templates/${id}`, body),
  deleteBehaviorTemplate: (id: number) => api.del<void>(`/api/behavior-templates/${id}`),
  applicationTemplates: () => api.get<ApplicationTemplate[]>("/api/application-templates"),
  createApplicationTemplate: (body: {
    name: string;
    display_name?: string;
    category?: string;
    template_config: Record<string, unknown>;
    os_type: string;
  }) => api.post<ApplicationTemplate>("/api/application-templates", body),
  updateApplicationTemplate: (id: number, body: Partial<ApplicationTemplate>) =>
    api.put<ApplicationTemplate>(`/api/application-templates/${id}`, body),
  deleteApplicationTemplate: (id: number) => api.del<void>(`/api/application-templates/${id}`),
  generatePlugin: (body: { name: string; os_type: string; description?: string }) =>
    api.post<{ name: string; os_type: string; template_config: Record<string, unknown> }>(
      "/api/application-templates/generate",
      body,
    ),
  mlStatus: () => api.get<MlStatus>("/api/ml/status"),
  mlReload: () => api.post<{ reloaded: boolean }>("/api/ml/reload", {}),
  meta: () => api.get<Meta>("/api/meta"),
  liveFleet: () => api.get<{ agents: FleetAgent[] }>("/api/live/fleet"),
  liveEvents: (after?: number | null, limit = 50) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (after != null) params.set("after", String(after));
    return api.get<LiveEventsResponse>(`/api/live/events?${params.toString()}`);
  },
  agents: () => api.get<Agent[]>("/api/agents"),
  agentStatus: (agentId: string) => api.get<AgentStatus>(`/api/agents/${agentId}/status`),
  agentHeartbeats: (agentId: string) => api.get<HeartbeatLog>(`/api/agents/${agentId}/heartbeats`),
  // config + next-activity are agent-token endpoints; the operator reads them
  // best-effort (silent on 401 so a missing agent token doesn't log the
  // operator out — see RequestOptions.silent401).
  agentConfig: (agentId: string) =>
    api.get<DeploymentPackage>(`/api/agents/${agentId}/config`, { silent401: true }),
  nextActivity: (agentId: string) =>
    api.get<NextActivity>(`/api/agents/${agentId}/next-activity`, { silent401: true }),
  deployments: (agentId: string) => api.get<Deployment[]>(`/api/agents/${agentId}/deployments`),
  deployAgent: (agentId: string, body: DeployRequest) =>
    api.post<Deployment>(`/api/agents/${agentId}/deploy`, body),
  diagnoseAgent: (agentId: string) => api.post<Diagnosis>(`/api/agents/${agentId}/diagnose`, {}),
  generateAgent: (body: Record<string, unknown>) =>
    api.post<GenerateAgentResponse>("/api/agents/generate", body),
  generateTemplate: (body: Record<string, unknown>) =>
    api.post<{
      name: string;
      os_type: string;
      template_data: Record<string, unknown>;
      source: string;
    }>("/api/behavior-templates/generate", body),
};
