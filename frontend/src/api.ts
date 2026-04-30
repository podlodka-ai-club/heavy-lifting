export type Prompt = {
  id: number;
  prompt_key: string;
  source_path: string;
  content: string;
  created_at: string;
  updated_at: string;
};

export type RuntimeSetting = {
  id: number;
  setting_key: string;
  env_var: string;
  value_type: "int" | "string";
  value: string;
  default_value: string;
  description: string;
  display_order: number;
  requires_restart: boolean;
  created_at: string;
  updated_at: string;
};

export type FactoryStation = {
  name: "fetch" | "execute" | "pr_feedback" | "deliver";
  counts_by_status: {
    new: number;
    processing: number;
    done: number;
    failed: number;
  };
  total_count: number;
  wip_count: number;
  queue_count: number;
  active_count: number;
  failed_count: number;
  oldest_queue_age_seconds: number | null;
  oldest_active_age_seconds: number | null;
};

export type FactorySnapshot = {
  generated_at: string;
  stations: FactoryStation[];
  bottleneck: {
    station: FactoryStation["name"];
    wip_count: number;
  } | null;
  data_gaps: string[];
};

export type EconomicsRoot = {
  root_task_id: number;
  external_task_id: string | null;
  tracker_name: string | null;
  closed_at: string;
  revenue_usd: string | null;
  token_cost_usd: string;
  profit_usd: string | null;
  revenue_source: "mock" | "expert" | "external" | null;
  revenue_confidence: "estimated" | "actual" | null;
};

export type EconomicsSeriesPoint = {
  bucket: string;
  closed_roots_count: number;
  monetized_roots_count: number;
  missing_revenue_count: number;
  revenue_usd: string;
  token_cost_usd: string;
  profit_usd: string;
};

export type EconomicsSnapshot = {
  generated_at: string;
  period: {
    from: string | null;
    to: string | null;
    bucket: "day" | "week" | "month";
  };
  totals: {
    closed_roots_count: number;
    monetized_roots_count: number;
    missing_revenue_count: number;
    revenue_usd: string;
    token_cost_usd: string;
    profit_usd: string;
  };
  series: EconomicsSeriesPoint[];
  roots: EconomicsRoot[];
  data_gaps: string[];
};

export type MockRevenueResult = {
  created_count: number;
  updated_count: number;
  created_root_task_ids: number[];
  updated_root_task_ids: number[];
};

export type RevenueUpsertPayload = {
  amount_usd: string;
  source: "expert" | "external";
  confidence: "estimated" | "actual";
  metadata?: Record<string, unknown> | null;
};

export type TaskRevenue = {
  id: number;
  root_task_id: number;
  amount_usd: string;
  source: "mock" | "expert" | "external";
  confidence: "estimated" | "actual";
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

type PromptListResponse = {
  prompts: Prompt[];
};

type PromptResponse = {
  prompt: Prompt;
};

type RuntimeSettingsListResponse = {
  settings: RuntimeSetting[];
};

type RuntimeSettingResponse = {
  setting: RuntimeSetting;
};

async function parseJsonResponse<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as T | { error?: string };

  if (!response.ok) {
    const message =
      typeof payload === "object" &&
      payload !== null &&
      "error" in payload &&
      typeof payload.error === "string"
        ? payload.error
        : "Backend request failed";
    throw new Error(message);
  }

  return payload as T;
}

export async function listPrompts(): Promise<Prompt[]> {
  const response = await fetch("/api/prompts");
  const payload = await parseJsonResponse<PromptListResponse>(response);
  return payload.prompts;
}

export async function updatePrompt(promptKey: string, content: string): Promise<Prompt> {
  const response = await fetch(`/api/prompts/${encodeURIComponent(promptKey)}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ content })
  });
  const payload = await parseJsonResponse<PromptResponse>(response);
  return payload.prompt;
}

export async function listRuntimeSettings(): Promise<RuntimeSetting[]> {
  const response = await fetch("/api/settings");
  const payload = await parseJsonResponse<RuntimeSettingsListResponse>(response);
  return payload.settings;
}

export async function updateRuntimeSetting(
  settingKey: string,
  value: string
): Promise<RuntimeSetting> {
  const response = await fetch(`/api/settings/${encodeURIComponent(settingKey)}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ value })
  });
  const payload = await parseJsonResponse<RuntimeSettingResponse>(response);
  return payload.setting;
}

export async function getFactorySnapshot(): Promise<FactorySnapshot> {
  const response = await fetch("/api/factory");
  return parseJsonResponse<FactorySnapshot>(response);
}

export async function getEconomicsSnapshot(): Promise<EconomicsSnapshot> {
  const response = await fetch("/api/economics");
  return parseJsonResponse<EconomicsSnapshot>(response);
}

export async function generateMockRevenue(): Promise<MockRevenueResult> {
  const response = await fetch("/api/economics/mock-revenue", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({})
  });
  return parseJsonResponse<MockRevenueResult>(response);
}

export async function upsertRevenue(
  rootTaskId: number,
  payload: RevenueUpsertPayload
): Promise<TaskRevenue> {
  const response = await fetch(`/api/economics/revenue/${rootTaskId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  const data = await parseJsonResponse<{ revenue: TaskRevenue }>(response);
  return data.revenue;
}
