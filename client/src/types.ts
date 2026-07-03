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
  skills: Array<{ name: string; status: string }>;
  tools: Array<{ name: string; status: string }>;
  sandbox: {
    image: string;
    available: boolean;
    approval_required: boolean;
    network: string;
    memory: string;
    cpu: string;
  };
};
