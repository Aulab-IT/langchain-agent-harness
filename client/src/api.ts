import type {
  CanaryAnalysis,
  ContextData,
  CronPreview,
  ConfigVersion,
  EvaluationArtifact,
  ImproveResult,
  ImprovementDetail,
  ImprovementSummary,
  ModelOverride,
  Run,
  RunEvent,
  PromotionResult,
  ProviderSettings,
  ProviderSettingsUpdate,
  RuntimeStatus,
  SessionDetail,
  SessionFile,
  SessionSandbox,
  SessionSummary,
  Skill,
  SkillDetail,
  SkillFile,
  SkillFileContent,
  SkillInstall,
  SkillInstallSource,
  ToolDescriptor,
  Trigger,
} from "./types";

const API_URL = (import.meta.env.VITE_HARNESS_API_URL as string | undefined) ?? "";

type ValidationIssue = { loc?: unknown[]; msg?: string };

/**
 * FastAPI usa `detail` per due cose diverse: una stringa per gli errori che solleviamo noi
 * (`HTTPException`), e una lista di oggetti per gli errori di validazione dello schema (422).
 * Concatenarla in un messaggio d'errore produce `[object Object]`, che non aiuta nessuno.
 */
function errorMessage(payload: unknown, status: number): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const issues = (detail as ValidationIssue[])
      .map((issue) => {
        const field = Array.isArray(issue.loc) ? issue.loc.slice(1).join(".") : "";
        return field ? `${field}: ${issue.msg ?? ""}` : (issue.msg ?? "");
      })
      .filter(Boolean);
    if (issues.length) return issues.join(" · ");
  }
  return `Errore API ${status}`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, options);
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    throw new Error(errorMessage(payload, response.status));
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

export function getProviderSettings(): Promise<ProviderSettings> {
  return request("/api/settings/providers");
}

export function updateProviderSettings(body: ProviderSettingsUpdate): Promise<ProviderSettings> {
  return request("/api/settings/providers", jsonOptions("PUT", body));
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

export function getSessionContext(sessionId: string): Promise<ContextData> {
  return request(`/api/sessions/${sessionId}/context`);
}

export function renameSession(sessionId: string, title: string): Promise<SessionSummary> {
  return request(`/api/sessions/${sessionId}`, jsonOptions("PATCH", { title }));
}

export function setSessionAutoApprove(
  sessionId: string,
  enabled: boolean,
): Promise<SessionSummary> {
  return request(
    `/api/sessions/${sessionId}/auto-approve`,
    jsonOptions("PATCH", { enabled }),
  );
}

export function deleteSession(sessionId: string): Promise<void> {
  return request(`/api/sessions/${sessionId}`, { method: "DELETE" });
}

export function stopSandbox(sessionId: string): Promise<SessionSandbox> {
  return request(`/api/sessions/${sessionId}/sandbox/stop`, { method: "POST" });
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
  "config.selected",
  "tool.started",
  "tool.completed",
  "tool.failed",
  "skill.started",
  "skill.completed",
  "grader.started",
  "grader.completed",
  "approval.requested",
  "approval.resolved",
  "approval.auto",
  "action.requested",
  "action.resolved",
  "assistant.delta",
  "assistant.iteration",
  "model.selected",
  "model.escalated",
  "usage.live",
  "usage.snapshot",
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

export function submitAction(
  runId: string,
  body: { response?: string; cancel?: boolean },
): Promise<{ status: string }> {
  return request(`/api/runs/${runId}/action`, jsonOptions("POST", body));
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

/** Serve inline solo immagini raster e PDF; per gli altri tipi il backend risponde 415. */
export function filePreviewUrl(sessionId: string, fileName: string): string {
  return `${API_URL}/api/sessions/${sessionId}/preview/${encodeURIComponent(fileName)}`;
}

// --- Loop 3: triggers ---

export function listTriggers(): Promise<Trigger[]> {
  return request("/api/triggers");
}

export function createTrigger(body: {
  kind: "cron" | "webhook";
  name: string;
  goal_template: string;
  cron_expr?: string | null;
  session_id?: string | null;
  timezone?: string;
  success_criteria?: string;
}): Promise<Trigger> {
  return request("/api/triggers", jsonOptions("POST", body));
}

export function previewCron(cron_expr: string, timezone: string): Promise<CronPreview> {
  return request("/api/triggers/preview", jsonOptions("POST", { cron_expr, timezone }));
}

export function toggleTrigger(triggerId: string, enabled: boolean): Promise<Trigger> {
  return request(`/api/triggers/${triggerId}`, jsonOptions("PATCH", { enabled }));
}

export function deleteTrigger(triggerId: string): Promise<void> {
  return request(`/api/triggers/${triggerId}`, { method: "DELETE" });
}

export function fireWebhook(
  triggerId: string,
  token: string,
  payload: unknown,
): Promise<{ status: string; run_id: string | null }> {
  return request(`/api/triggers/${triggerId}/webhook`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Trigger-Token": token },
    body: JSON.stringify(payload ?? {}),
  });
}

export function webhookUrl(triggerId: string): string {
  const base = API_URL || window.location.origin;
  return `${base}/api/triggers/${triggerId}/webhook`;
}

// --- Loop 4: hill-climbing improvements ---

export function listImprovements(): Promise<ImprovementSummary[]> {
  return request("/api/improvements");
}

export function getImprovement(name: string): Promise<ImprovementDetail> {
  return request(`/api/improvements/${encodeURIComponent(name)}`);
}

export function runImprove(since: number): Promise<ImproveResult> {
  return request("/api/improve", jsonOptions("POST", { since }));
}

// --- Agent Skills (standard agentskills.io) ---

export function listSkills(): Promise<Skill[]> {
  return request("/api/skills");
}

export function setSessionModelOverride(
  sessionId: string,
  override: ModelOverride,
): Promise<SessionSummary> {
  return request(`/api/sessions/${sessionId}/model`, jsonOptions("PATCH", { override }));
}

export function getTemplateMemory(): Promise<{ content: string }> {
  return request("/api/memory");
}

export function putTemplateMemory(content: string): Promise<{ content: string }> {
  return request("/api/memory", jsonOptions("PUT", { content }));
}

export function getSessionMemory(sessionId: string): Promise<{ content: string }> {
  return request(`/api/sessions/${sessionId}/memory`);
}

export function putSessionMemory(
  sessionId: string,
  content: string,
): Promise<{ content: string }> {
  return request(`/api/sessions/${sessionId}/memory`, jsonOptions("PUT", { content }));
}

export function promoteSessionMemory(sessionId: string): Promise<{ content: string }> {
  return request(`/api/sessions/${sessionId}/memory/promote`, { method: "POST" });
}

export function listTools(): Promise<ToolDescriptor[]> {
  return request("/api/tools");
}

export function getSkill(name: string): Promise<SkillDetail> {
  return request(`/api/skills/${encodeURIComponent(name)}`);
}

export function createSkill(body: {
  name: string;
  description: string;
  body: string;
}): Promise<SkillDetail> {
  return request("/api/skills", jsonOptions("POST", body));
}

export function updateSkill(name: string, content: string): Promise<SkillDetail> {
  return request(`/api/skills/${encodeURIComponent(name)}`, jsonOptions("PUT", { content }));
}

export function deleteSkill(name: string): Promise<void> {
  return request(`/api/skills/${encodeURIComponent(name)}`, { method: "DELETE" });
}

export function installSkillCreator(force = false): Promise<SkillDetail> {
  return request(`/api/skills/install/skill-creator?force=${force}`, { method: "POST" });
}

export function installSkill(body: {
  source: SkillInstallSource;
  value: string;
  ref?: string | null;
  subdir?: string | null;
  force?: boolean;
}): Promise<SkillDetail> {
  return request("/api/skills/install", jsonOptions("POST", body));
}

export function listSkillInstalls(): Promise<SkillInstall[]> {
  return request("/api/skills/installs");
}

export function listSkillFiles(name: string): Promise<SkillFile[]> {
  return request(`/api/skills/${encodeURIComponent(name)}/files`);
}

export function getSkillFile(name: string, path: string): Promise<SkillFileContent> {
  return request(`/api/skills/${encodeURIComponent(name)}/files/${path}`);
}

export function putSkillFile(
  name: string,
  path: string,
  content: string,
): Promise<SkillFileContent> {
  return request(
    `/api/skills/${encodeURIComponent(name)}/files/${path}`,
    jsonOptions("PUT", { content }),
  );
}

export function deleteSkillFile(name: string, path: string): Promise<void> {
  return request(`/api/skills/${encodeURIComponent(name)}/files/${path}`, { method: "DELETE" });
}

export async function uploadSkillFile(name: string, file: File): Promise<SkillFileContent> {
  const form = new FormData();
  form.append("file", file);
  return request(`/api/skills/${encodeURIComponent(name)}/files`, {
    method: "POST",
    body: form,
  });
}

export function evaluateImprovement(name: string): Promise<EvaluationArtifact> {
  return request(`/api/improvements/${encodeURIComponent(name)}/evaluate`, {
    method: "POST",
  });
}

export function applyImprovement(
  name: string,
  mode: "canary" | "full",
  fraction = 0.2,
): Promise<PromotionResult> {
  return request(
    `/api/improvements/${encodeURIComponent(name)}/apply`,
    jsonOptions("POST", { mode, fraction }),
  );
}

export function clearOverrides(): Promise<void> {
  return request("/api/overrides", { method: "DELETE" });
}

export function clearCanary(): Promise<void> {
  return request("/api/canary", { method: "DELETE" });
}

export function getCanaryStatus(): Promise<CanaryAnalysis> {
  return request("/api/canary/status");
}

export function listConfigVersions(): Promise<ConfigVersion[]> {
  return request("/api/config/versions");
}

export function restoreConfigVersion(id: string): Promise<{ overrides: Record<string, unknown> }> {
  return request(`/api/config/versions/${encodeURIComponent(id)}/restore`, {
    method: "POST",
  });
}
