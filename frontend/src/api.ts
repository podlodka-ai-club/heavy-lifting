export type Prompt = {
  id: number;
  prompt_key: string;
  source_path: string;
  content: string;
  created_at: string;
  updated_at: string;
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
  const response = await fetch("/prompts");
  const payload = await parseJsonResponse<PromptListResponse>(response);
  return payload.prompts;
}

export async function updatePrompt(promptKey: string, content: string): Promise<Prompt> {
  const response = await fetch(`/prompts/${encodeURIComponent(promptKey)}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ content })
  });
  const payload = await parseJsonResponse<PromptResponse>(response);
  return payload.prompt;
}
