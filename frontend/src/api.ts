import type { SettingsResponse, SettingsUpdateRequest } from "./types";

async function parseResponse<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as T;
  if (!response.ok) {
    const message =
      typeof payload === "object" && payload !== null && "error" in payload
        ? String((payload as { error: unknown }).error)
        : `Request failed with ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

export async function getSettings(): Promise<SettingsResponse> {
  return parseResponse<SettingsResponse>(await fetch("/settings"));
}

export async function updateSettings(
  payload: SettingsUpdateRequest
): Promise<SettingsResponse> {
  return parseResponse<SettingsResponse>(
    await fetch("/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
  );
}
