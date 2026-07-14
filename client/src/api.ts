import type {
  CanaryAnalysis,
  ContextData,
  CostSummary,
  CronPreview,
  ConfigVersion,
  EvaluationArtifact,
  EventPage,
  ImproveResult,
  ImprovementDetail,
  ImprovementSummary,
  McpStatus,
  ModelTier,
  ModelOverride,
  Rubric,
  RuntimeField,
  Run,
  RunEvidence,
  RunEvent,
  PromotionResult,
  ProviderModels,
  ProviderName,
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
  Subagent,
  SubagentDetail,
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

export function getProviderModels(provider: ProviderName): Promise<ProviderModels> {
  return request(`/api/settings/providers/${provider}/models`);
}

export function getMcpConfig(): Promise<{ content: string }> {
  return request("/api/settings/mcp");
}

export function updateMcpConfig(content: string): Promise<{ content: string; servers: string[] }> {
  return request("/api/settings/mcp", jsonOptions("PUT", { content }));
}

export function getMcpStatus(): Promise<McpStatus> {
  return request("/api/settings/mcp/status");
}

export function getRubric(): Promise<Rubric> {
  return request("/api/rubric");
}

export function getCosts(): Promise<CostSummary> {
  return request("/api/costs");
}

export function getRuntimeSettings(): Promise<{ fields: RuntimeField[] }> {
  return request("/api/settings/runtime");
}

export function updateRuntimeSettings(
  values: Record<string, number>,
): Promise<{ fields: RuntimeField[] }> {
  return request("/api/settings/runtime", jsonOptions("PUT", { values }));
}

export function setTriggerScheduler(
  enabled: boolean,
): Promise<{ enabled: boolean; tick_seconds: number }> {
  return request("/api/settings/triggers", jsonOptions("PUT", { enabled }));
}

export function compactContext(sessionId: string): Promise<{ run_id: string; status: string }> {
  return request(`/api/sessions/${sessionId}/context/compact`, jsonOptions("POST"));
}

export type AppNotification = {
  id: number;
  session_id: string | null;
  run_id: string | null;
  type: string;
  title: string;
  read: boolean;
  created_at: string;
};

export function getNotifications(
  unread = false,
): Promise<{ unread_count: number; notifications: AppNotification[] }> {
  return request(`/api/notifications${unread ? "?unread=true" : ""}`);
}

export function markNotificationsRead(ids: number[] | null = null): Promise<{ unread_count: number }> {
  return request("/api/notifications/read", jsonOptions("POST", { ids }));
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

export function getRunEvidence(runId: string): Promise<RunEvidence> {
  return request(`/api/runs/${runId}/evidence`);
}

export function getSessionEventPage(
  sessionId: string,
  before?: number,
): Promise<EventPage> {
  const query = before ? `?before=${before}` : "";
  return request(`/api/sessions/${sessionId}/event-history${query}`);
}

export function getRunEventPage(runId: string, before?: number): Promise<EventPage> {
  const query = before ? `?before=${before}` : "";
  return request(`/api/runs/${runId}/event-history${query}`);
}

export function subscribeRun(
  runId: string,
  onEvent: (event: RunEvent) => void,
  onDisconnect: () => void,
): () => void {
  const source = new EventSource(`${API_URL}/api/runs/${runId}/events`);
  source.onmessage = (message) => onEvent(JSON.parse(message.data) as RunEvent);
  source.onerror = () => {
    source.close();
    onDisconnect();
  };
  return () => {
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

export type PreviewText = {
  content: string;
  kind: "text" | "markdown" | "csv";
  truncated: boolean;
};

export function getPreviewText(sessionId: string, fileName: string): Promise<PreviewText> {
  return request(`/api/sessions/${sessionId}/preview-text/${encodeURIComponent(fileName)}`);
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
  auto_approve?: boolean;
  model_tier?: "auto" | "low" | "mid" | "high";
  text_response?: boolean;
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

export function listSubagents(): Promise<Subagent[]> {
  return request("/api/subagents");
}

export function getSubagent(name: string): Promise<SubagentDetail> {
  return request(`/api/subagents/${encodeURIComponent(name)}`);
}

export type SubagentInput = {
  name: string;
  description: string;
  system_prompt: string;
  model_tier: ModelTier;
  capabilities: string[];
  inputs: string[];
  outputs: string[];
  constraints: string[];
  tools: string[];
  read_only: boolean;
};

export function createSubagent(input: SubagentInput): Promise<SubagentDetail> {
  return request("/api/subagents", jsonOptions("POST", input));
}

export function updateSubagent(
  name: string,
  input: Omit<SubagentInput, "name">,
): Promise<SubagentDetail> {
  return request(`/api/subagents/${encodeURIComponent(name)}`, jsonOptions("PUT", input));
}

export function deleteSubagent(name: string): Promise<void> {
  return request(`/api/subagents/${encodeURIComponent(name)}`, { method: "DELETE" });
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

export type SessionMemory = {
  content: string;
  chars: number;
  tokens: number;
  max_chars: number;
};

export function getSessionMemory(sessionId: string): Promise<SessionMemory> {
  return request(`/api/sessions/${sessionId}/memory`);
}

export function putSessionMemory(sessionId: string, content: string): Promise<SessionMemory> {
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
