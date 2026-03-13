import { sessionHeaders, type SessionUser } from "@/lib/session";

export type AgentSummary = {
  id: string;
  display_name: string;
  label: string;
  persona_json?: {
    core_beliefs?: string[];
    values?: string[];
  };
  vector?: number[];
};

export type ThreadSummary = {
  id: string;
  topic: string;
  topic_tags?: string[];
  agent_ids: string[];
  state: string;
  visibility: string;
  speed_mode?: string;
  max_posts?: number;
  created_at: string;
  post_count?: number;
};

export type PostRecord = {
  id: number;
  agent_id: string | null;
  display_name?: string;
  label?: string;
  reply_to: number | null;
  content: string;
  stance?: string | null;
  focus_axis?: string | null;
  is_facilitator: boolean;
  created_at: string;
};

export function getApiBaseUrl() {
  return process.env.NEXT_PUBLIC_API_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

export function getWsBaseUrl() {
  const ws = process.env.NEXT_PUBLIC_WS_URL;
  if (ws) return ws;
  const api = process.env.NEXT_PUBLIC_API_URL ?? "";
  if (api) return api.replace(/^https:\/\//, "wss://").replace(/^http:\/\//, "ws://");
  return "ws://localhost:8000";
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  user?: SessionUser | null
): Promise<T> {
  const headers = new Headers(init.headers);
  const authHeaders = sessionHeaders(user);
  Object.entries(authHeaders).forEach(([key, value]) => {
    headers.set(key, String(value));
  });
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers,
    cache: "no-store"
  });

  if (!response.ok) {
    let detail = "Request failed";
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      detail = await response.text();
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null as T;
  }
  return response.json() as Promise<T>;
}
