export type AgentStatus = "idle" | "thinking" | "working" | "approval" | "error";

export type Usage = {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  output_tokens_per_second: number;
  context_categories: Array<{
    name: string;
    tokens: number;
    percent: number;
    color: string;
  }>;
  estimated_context: boolean;
};

export type Message = {
  id: string;
  session_id: string;
  run_id: string | null;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  attachments: string[];
};

export type SessionFile = {
  name: string;
  size: number;
  type: string;
  modified_at?: string;
};

export type Run = {
  id: string;
  session_id: string;
  status:
    | "queued"
    | "running"
    | "waiting_approval"
    | "completed"
    | "failed"
    | "cancelled";
  started_at: string;
  completed_at: string | null;
  error: string | null;
  usage: Usage;
};

export type SessionSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  preview?: string | null;
  last_status?: string | null;
  auto_approve: boolean;
};

export type SessionSandbox = {
  state: "idle" | "running" | "unavailable";
  container: string | null;
  running: boolean;
  image: string;
};

export type SessionDetail = SessionSummary & {
  messages: Message[];
  files: SessionFile[];
  latest_run: Run | null;
  events: RunEvent[];
  trace_events: RunEvent[];
  sandbox: SessionSandbox;
};

export type RunEvent = {
  id: number;
  run_id: string;
  session_id: string;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type ActivityItem = {
  id: string;
  name: string;
  detail: string;
  status: "active" | "ready" | "error";
  meta?: string;
};

export type RuntimeStatus = {
  backend: "online";
  configured: boolean;
  model: string;
  strong_model: string;
  context_window: number;
  skills: Array<{ name: string; status: string; description?: string }>;
  tools: Array<{ name: string; status: string }>;
  sandbox: {
    image: string;
    available: boolean;
    approval_required: boolean;
    network: string;
    memory: string;
    cpu: string;
  };
  verification: { enabled: boolean; threshold: number };
  triggers: { enabled: boolean; tick_seconds: number };
  overrides: Record<string, unknown>;
  canary: CanaryConfig | null;
};

export type Skill = {
  name: string;
  declared_name: string | null;
  description: string;
  license: string | null;
  compatibility: string | null;
  allowed_tools: string | null;
  metadata: Record<string, string>;
  has_scripts: boolean;
  has_references: boolean;
  has_assets: boolean;
  body_lines: number;
  valid: boolean;
  errors: string[];
};

export type SkillDetail = Skill & { content: string };

export type Trigger = {
  id: string;
  kind: "cron" | "webhook";
  name: string;
  cron_expr: string | null;
  token: string | null;
  goal_template: string;
  session_id: string | null;
  enabled: boolean;
  created_at: string;
  last_fired_at: string | null;
};

export type ImprovementSummary = {
  name: string;
  size: number;
  modified_at: string;
  evaluation_status: "pending" | "passed" | "rejected" | "stale";
};

export type ImprovementDetail = {
  name: string;
  content: string;
  overrides: Record<string, unknown>;
  evaluation: EvaluationArtifact | null;
};

export type CaseResult = {
  case_id: string;
  passed: boolean;
  score: number;
  completed: boolean;
  tokens: number;
  elapsed_ms: number;
  failures: string[];
  error: string;
};

export type ArmSummary = {
  pass_rate: number;
  avg_score: number;
  total_tokens: number;
  elapsed_ms: number;
};

export type EvaluationArtifact = {
  evaluation_id: string;
  proposal_name: string;
  created_at: string;
  eval_set_hash: string;
  baseline_fingerprint: string;
  candidate_fingerprint: string;
  baseline: CaseResult[];
  candidate: CaseResult[];
  baseline_summary: ArmSummary;
  candidate_summary: ArmSummary;
  gate: {
    passed: boolean;
    quality_delta: number;
    token_ratio: number;
    latency_ratio: number;
    regressions: string[];
    reasons: string[];
  };
};

export type CanaryConfig = {
  source: string;
  created_at: string;
  fraction: number;
  baseline_fingerprint: string;
  candidate_fingerprint: string;
  overrides: Record<string, unknown>;
};

export type PromotionResult = {
  mode: "canary" | "full";
  active: Record<string, unknown>;
  canary: CanaryConfig | null;
  version: ConfigVersion | null;
};

export type ConfigVersion = {
  id: string;
  created_at: string;
  source: string;
  fingerprint: string;
  overrides: Record<string, unknown>;
};

export type ContextEntry = {
  index: number;
  kind: "system" | "memory" | "user" | "assistant" | "tool" | "other";
  role: string;
  name: string | null;
  text: string;
  tool_calls: Array<{ name: string; args: string }>;
  tokens: number;
  category: string;
};

export type ContextData = {
  total_tokens: number;
  context_window: number;
  categories: Array<{ name: string; tokens: number; percent: number; color: string }>;
  entries: ContextEntry[];
};

export type ImproveResult = {
  name: string;
  summary: string;
  findings: string[];
  overrides: Record<string, unknown>;
  report: string;
};
