import type {
  Run,
  RunEvent,
  RuntimeStatus,
  SessionDetail,
  SessionFile,
  SessionSummary,
} from "./types";

const API_URL = (import.meta.env.VITE_HARNESS_API_URL as string | undefined) ?? "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, options);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `Errore API ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function jsonOptions(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

export function getRuntimeStatus(): Promise<RuntimeStatus> {
  return request("/api/status");
}

export function listSessions(search = ""): Promise<SessionSummary[]> {
  const query = search ? `?search=${encodeURIComponent(search)}` : "";
  return request(`/api/sessions${query}`);
}

export function createSession(title = "Nuova sessione"): Promise<SessionSummary> {
  return request("/api/sessions", jsonOptions("POST", { title }));
}

export function getSession(sessionId: string): Promise<SessionDetail> {
  return request(`/api/sessions/${sessionId}`);
}

export function renameSession(sessionId: string, title: string): Promise<SessionSummary> {
  return request(`/api/sessions/${sessionId}`, jsonOptions("PATCH", { title }));
}

export function deleteSession(sessionId: string): Promise<void> {
  return request(`/api/sessions/${sessionId}`, { method: "DELETE" });
}

export function sendMessage(
  sessionId: string,
  content: string,
  attachments: string[] = [],
): Promise<{ run_id: string; status: string }> {
  return request(
    `/api/sessions/${sessionId}/messages`,
    jsonOptions("POST", { content, attachments }),
  );
}

export function getRun(runId: string): Promise<Run> {
  return request(`/api/runs/${runId}`);
}

const RUN_EVENT_TYPES = [
  "run.started",
  "agent.started",
  "tool.started",
  "tool.completed",
  "tool.failed",
  "skill.started",
  "skill.completed",
  "approval.requested",
  "approval.resolved",
  "assistant.delta",
  "usage.live",
  "usage.updated",
  "assistant.completed",
  "file.created",
  "file.updated",
  "run.completed",
  "run.failed",
  "run.cancelled",
];

export function subscribeRun(
  runId: string,
  onEvent: (event: RunEvent) => void,
  onDisconnect: () => void,
): () => void {
  const source = new EventSource(`${API_URL}/api/runs/${runId}/events`);
  const listeners = new Map<string, EventListener>();
  for (const type of RUN_EVENT_TYPES) {
    const listener: EventListener = (raw) => {
      const message = raw as MessageEvent<string>;
      onEvent(JSON.parse(message.data) as RunEvent);
    };
    listeners.set(type, listener);
    source.addEventListener(type, listener);
  }
  source.onerror = () => {
    source.close();
    onDisconnect();
  };
  return () => {
    for (const [type, listener] of listeners) {
      source.removeEventListener(type, listener);
    }
    source.close();
  };
}

export function approveRun(runId: string): Promise<{ status: string }> {
  return request(`/api/runs/${runId}/approve`, { method: "POST" });
}

export function rejectRun(runId: string): Promise<{ status: string }> {
  return request(`/api/runs/${runId}/reject`, { method: "POST" });
}

export function cancelRun(runId: string): Promise<{ status: string }> {
  return request(`/api/runs/${runId}/cancel`, { method: "POST" });
}

export async function uploadContextFile(
  sessionId: string,
  file: File,
): Promise<SessionFile> {
  const body = new FormData();
  body.append("file", file);
  return request(`/api/sessions/${sessionId}/files`, { method: "POST", body });
}

export function deleteContextFile(sessionId: string, fileName: string): Promise<void> {
  return request(
    `/api/sessions/${sessionId}/files/${encodeURIComponent(fileName)}`,
    { method: "DELETE" },
  );
}

export function fileDownloadUrl(sessionId: string, fileName: string): string {
  return `${API_URL}/api/sessions/${sessionId}/files/${encodeURIComponent(fileName)}`;
}
