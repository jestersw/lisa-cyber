const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

let authToken: string | null = null;

export function setToken(token: string | null): void {
  authToken = token;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (authToken) {
    headers.set("Authorization", `Bearer ${authToken}`);
  }

  const response = await fetch(`${BASE_URL}${path}`, { ...init, headers });

  if (response.status === 401) {
    setToken(null);
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
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export interface Role {
  id: number;
  name: string;
  description: string;
  category: string;
}

export interface BehaviorTemplate {
  id: number;
  name: string;
  role_id: number;
  os_type: string;
  template_data: { applications_used?: string[] };
}

export interface ApplicationTemplate {
  id: number;
  name: string;
  display_name: string | null;
  category: string | null;
  os_type: string;
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
  config_url: string;
  status_url: string;
}


export interface AgentStatus {
  agent: {
    agent_id: string;
    name: string;
    status: string;
    os_type: string;
    role: string | null;
    last_seen: string | null;
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
  roles: () => api.get<Role[]>("/api/roles"),
  behaviorTemplates: () => api.get<BehaviorTemplate[]>("/api/behavior-templates"),
  applicationTemplates: () => api.get<ApplicationTemplate[]>("/api/application-templates"),
  agents: () => api.get<Agent[]>("/api/agents"),
  agentStatus: (agentId: string) => api.get<AgentStatus>(`/api/agents/${agentId}/status`),
  agentHeartbeats: (agentId: string) => api.get<HeartbeatLog>(`/api/agents/${agentId}/heartbeats`),
  agentConfig: (agentId: string) => api.get<DeploymentPackage>(`/api/agents/${agentId}/config`),
  nextActivity: (agentId: string) => api.get<NextActivity>(`/api/agents/${agentId}/next-activity`),
  generateAgent: (body: Record<string, unknown>) =>
    api.post<GenerateAgentResponse>("/api/agents/generate", body),
  generateTemplate: (body: Record<string, unknown>) =>
    api.post<{ name: string; template_data: Record<string, unknown> }>(
      "/api/behavior-templates/generate",
      body,
    ),
};
