export type Prompt = {
  id: number;
  prompt_key: string;
  source_path: string;
  content: string;
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

type PromptListResponse = {
  prompts: Prompt[];
};

type PromptResponse = {
  prompt: Prompt;
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

export async function getFactorySnapshot(): Promise<FactorySnapshot> {
  const response = await fetch("/api/factory");
  return parseJsonResponse<FactorySnapshot>(response);
}
