import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const prompts = [
  {
    id: 1,
    prompt_key: "dev",
    source_path: "prompts/agents/dev.md",
    content: "DEV prompt",
    created_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00"
  },
  {
    id: 2,
    prompt_key: "review",
    source_path: "prompts/agents/review.md",
    content: "REVIEW prompt",
    created_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00"
  }
];

describe("App", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows the home page and opens settings from the top bar", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ prompts }))
    );

    render(<App />);

    expect(screen.getByRole("heading", { name: "heavy-lifting" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Настройки" }));

    expect(await screen.findByRole("heading", { name: "Промты агентов" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /dev/ })).toBeInTheDocument();
  });

  it("loads prompts, switches selection, and saves edited content", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input.toString();

      if (url === "/prompts" && !init) {
        return jsonResponse({ prompts });
      }

      if (url === "/prompts/review" && init?.method === "PATCH") {
        return jsonResponse({
          prompt: {
            ...prompts[1],
            content: "Updated REVIEW prompt"
          }
        });
      }

      return jsonResponse({ error: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.pushState({}, "", "/settings");

    render(<App />);

    const editor = await screen.findByLabelText("Content");
    expect(editor).toHaveValue("DEV prompt");

    await userEvent.click(screen.getByRole("button", { name: /review/ }));
    expect(screen.getByLabelText("Content")).toHaveValue("REVIEW prompt");

    await userEvent.clear(screen.getByLabelText("Content"));
    await userEvent.type(screen.getByLabelText("Content"), "Updated REVIEW prompt");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/prompts/review",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ content: "Updated REVIEW prompt" })
        })
      )
    );
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
  });

  it("shows backend errors while loading prompts", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "Backend unavailable" }, 500)));
    window.history.pushState({}, "", "/settings");

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unavailable");
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json"
    }
  });
}
