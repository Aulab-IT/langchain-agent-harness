import type { Usage } from "../types";

export const ACCEPTED_FILES =
  ".csv,.docx,.gif,.html,.jpeg,.jpg,.json,.md,.pdf,.png,.pptx,.py,.sql,.svg,.tar,.toml,.ts,.tsx,.txt,.webp,.xlsx,.xml,.yaml,.yml,.zip";

export const EMPTY_USAGE: Usage = {
  input_tokens: 0,
  output_tokens: 0,
  total_tokens: 0,
  output_tokens_per_second: 0,
  context_categories: [],
  estimated_context: true,
};

export type View = "control" | "traces" | "skills" | "triggers" | "improve" | "settings";

export type InspectorTab = "files" | "capabilities" | "context" | "sandbox";
