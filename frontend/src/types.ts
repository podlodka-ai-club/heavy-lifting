export type ApiKeySettings = {
  configured: boolean;
  source: "runtime" | "env" | "none";
  env_var: string | null;
};

export type AgentPromptSettings = {
  name: string;
  prompt: string;
  source: "default" | "runtime";
};

export type SettingsResponse = {
  api_key: ApiKeySettings;
  agents: AgentPromptSettings[];
};

export type SettingsUpdateRequest = {
  api_key?: string | null;
  prompts?: Record<string, string>;
};
