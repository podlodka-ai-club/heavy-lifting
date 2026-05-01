import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

type TestFactoryStation = {
  name: string;
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

const runtimeSettings = [
  {
    id: 1,
    setting_key: "tracker_fetch_limit",
    env_var: "TRACKER_FETCH_LIMIT",
    value_type: "int",
    value: "100",
    default_value: "100",
    description: "Maximum tracker tasks fetched by worker1 in one poll.",
    display_order: 10,
    requires_restart: true,
    created_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00"
  },
  {
    id: 2,
    setting_key: "local_agent_model",
    env_var: "LOCAL_AGENT_MODEL",
    value_type: "string",
    value: "gpt-5.4",
    default_value: "gpt-5.4",
    description: "Model recorded by the local placeholder agent runner.",
    display_order: 40,
    requires_restart: true,
    created_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00"
  }
];

const factorySnapshot = {
  generated_at: "2026-04-30T12:00:00+00:00",
  stations: [
    factoryStation("fetch", {
      total_count: 1,
      wip_count: 1,
      queue_count: 1,
      oldest_queue_age_seconds: 620,
      counts_by_status: { new: 1, processing: 0, done: 0, failed: 0 }
    }),
    factoryStation("execute", {
      total_count: 3,
      wip_count: 3,
      queue_count: 2,
      active_count: 1,
      failed_count: 1,
      oldest_queue_age_seconds: 3660,
      oldest_active_age_seconds: 190,
      counts_by_status: { new: 2, processing: 1, done: 0, failed: 1 }
    }),
    factoryStation("pr_feedback", {
      total_count: 0,
      counts_by_status: { new: 0, processing: 0, done: 0, failed: 0 }
    }),
    factoryStation("deliver", {
      total_count: 2,
      counts_by_status: { new: 0, processing: 0, done: 2, failed: 0 }
    })
  ],
  bottleneck: {
    station: "execute",
    wip_count: 3
  },
  data_gaps: [
    "transition_history",
    "throughput_per_hour",
    "worker_capacity",
    "rework_loops",
    "business_task_kind"
  ]
};

const economicsSnapshot = {
  generated_at: "2026-04-30T12:00:00+00:00",
  period: {
    from: "2026-03-31T12:00:00+00:00",
    to: "2026-04-30T12:00:00+00:00",
    bucket: "day"
  },
  totals: {
    closed_roots_count: 2,
    monetized_roots_count: 1,
    missing_revenue_count: 1,
    revenue_usd: "1500.000000",
    token_cost_usd: "5.000000",
    profit_usd: "1495.000000"
  },
  series: [
    {
      bucket: "2026-04-28",
      closed_roots_count: 1,
      monetized_roots_count: 1,
      missing_revenue_count: 0,
      revenue_usd: "1500.000000",
      token_cost_usd: "4.750000",
      profit_usd: "1495.250000"
    },
    {
      bucket: "2026-04-29",
      closed_roots_count: 1,
      monetized_roots_count: 0,
      missing_revenue_count: 1,
      revenue_usd: "0.000000",
      token_cost_usd: "0.250000",
      profit_usd: "-0.250000"
    }
  ],
  roots: [
    {
      root_task_id: 10,
      external_task_id: "TASK-10",
      tracker_name: "mock",
      closed_at: "2026-04-28T10:00:00+00:00",
      revenue_usd: "1500.000000",
      token_cost_usd: "4.750000",
      profit_usd: "1495.250000",
      revenue_source: "expert",
      revenue_confidence: "actual"
    },
    {
      root_task_id: 11,
      external_task_id: "TASK-11",
      tracker_name: "mock",
      closed_at: "2026-04-29T12:00:00+00:00",
      revenue_usd: null,
      token_cost_usd: "0.250000",
      profit_usd: null,
      revenue_source: null,
      revenue_confidence: null
    }
  ],
  data_gaps: ["infra_cost", "runner_hours", "external_accounting_import", "retry_waste"]
};

const retroTags = [
  {
    tag: "acceptance-missing",
    count: 8,
    severity_counts: { error: 5, warning: 2, info: 1 },
    first_seen: "2026-04-28T10:00:00+00:00",
    last_seen: "2026-04-30T12:00:00+00:00",
    affected_tasks_count: 4
  },
  {
    tag: "slow-ci",
    count: 3,
    severity_counts: { warning: 3 },
    first_seen: "2026-04-29T10:00:00+00:00",
    last_seen: "2026-04-30T11:00:00+00:00",
    affected_tasks_count: 2
  },
  {
    tag: "trace-note",
    count: 1,
    severity_counts: { info: 1 },
    first_seen: "2026-04-30T09:00:00+00:00",
    last_seen: "2026-04-30T09:00:00+00:00",
    affected_tasks_count: 1
  }
];

const retroEntries = [
  {
    id: 101,
    task_id: 20,
    root_id: 10,
    task_type: "execute",
    role: "DEV",
    attempt: 1,
    source: "agent",
    category: "requirements",
    tag: "acceptance-missing",
    severity: "error",
    message: "Acceptance criteria were missing before implementation.",
    suggested_action: "Ask for concrete acceptance criteria before coding.",
    metadata: null,
    created_at: "2026-04-30T12:00:00+00:00"
  },
  {
    id: 102,
    task_id: 21,
    root_id: 10,
    task_type: "pr_feedback",
    role: "REVIEW",
    attempt: 1,
    source: "review",
    category: "requirements",
    tag: "acceptance-missing",
    severity: "warning",
    message: "Reviewer had to infer expected behavior.",
    suggested_action: null,
    metadata: {},
    created_at: "2026-04-30T12:10:00+00:00"
  }
];

describe("App", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/");
    mockReducedMotion(false);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows the home page and topbar links", () => {
    vi.stubGlobal("fetch", vi.fn());

    render(<App />);

    expect(screen.getByRole("heading", { name: "heavy-lifting" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Factory" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Factory v2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Money" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Money v2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retro" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Настройки" })).toBeInTheDocument();
  });

  it("opens factory from the topbar and shows loading state", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));

    render(<App />);

    await userEvent.click(screen.getByRole("button", { name: "Factory" }));

    expect(screen.getByRole("heading", { name: "Factory Flow" })).toBeInTheDocument();
    expect(screen.getByText("Загрузка factory...")).toBeInTheDocument();
  });

  it("loads factory snapshot and renders live station data with explicit gaps", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (input.toString() === "/api/factory") {
        return jsonResponse(factorySnapshot);
      }

      return jsonResponse({ error: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.pushState({}, "", "/factory");

    render(<App />);

    expect(await screen.findByText(/generated_at=/)).toBeInTheDocument();
    expect(screen.getByText("Current bottleneck")).toBeInTheDocument();
    expect(screen.getByText("WIP 3")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Factory handoff routes" })).toBeInTheDocument();
    expect(screen.getByLabelText("fetch payload marker")).toBeInTheDocument();
    expect(screen.getByLabelText("execute payload marker")).toBeInTheDocument();
    expect(document.querySelectorAll("animateMotion")).toHaveLength(2);

    const executeStation = screen.getByLabelText("execute station");
    expect(executeStation).toHaveClass("bottleneck");
    expect(within(executeStation).getByText("BOTTLENECK")).toBeInTheDocument();
    expect(within(executeStation).getByText("1h 1m")).toBeInTheDocument();
    expect(within(executeStation).getByText("3m")).toBeInTheDocument();
    expect(within(executeStation).getByText("failed 1")).toBeInTheDocument();
    expect(executeStation.querySelector(".station-machine")).not.toBeNull();

    const feedbackStation = screen.getByLabelText("pr feedback station");
    const zeroWipMeter = within(feedbackStation).getByLabelText("pr feedback WIP 0");
    expect(zeroWipMeter.firstElementChild).toHaveStyle({ minWidth: "0", width: "0%" });
    expect(screen.queryByLabelText("pr feedback payload marker")).not.toBeInTheDocument();

    expect(screen.getByText("Не показываем то, чего нет в API")).toBeInTheDocument();
    expect(screen.getByText("transition_history")).toBeInTheDocument();
    expect(screen.getByText("worker_capacity")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/factory");
  });

  it("keeps payload markers static when reduced motion is preferred", async () => {
    mockReducedMotion(true);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) =>
        input.toString() === "/api/factory"
          ? jsonResponse(factorySnapshot)
          : jsonResponse({ error: "not found" }, 404)
      )
    );
    window.history.pushState({}, "", "/factory");

    render(<App />);

    const fetchMarker = await screen.findByLabelText("fetch payload marker");
    expect(fetchMarker).toHaveAttribute("cx", "178");
    expect(fetchMarker).toHaveAttribute("cy", "334");
    expect(document.querySelector("animateMotion")).not.toBeInTheDocument();
  });

  it("shows backend errors while loading factory", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "Factory unavailable" }, 500)));
    window.history.pushState({}, "", "/factory");

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Factory unavailable");
  });

  it("opens factory v2 from the topbar and shows loading state", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));

    render(<App />);

    await userEvent.click(screen.getByRole("button", { name: "Factory v2" }));

    expect(screen.getByRole("heading", { name: "Factory Floor" })).toBeInTheDocument();
    expect(screen.getByText("Загрузка factory...")).toBeInTheDocument();
  });

  it("loads factory v2 from direct URL through the factory API", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (input.toString() === "/api/factory") {
        return jsonResponse(factorySnapshot);
      }

      return jsonResponse({ error: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.pushState({}, "", "/factory2");

    render(<App />);

    expect(await screen.findByText("GET /factory")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Factory Floor" })).toBeInTheDocument();
    expect(screen.getByText("execute wip=3 q=2")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/factory");
  });

  it("opens economics from the topbar and shows loading state", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));

    render(<App />);

    await userEvent.click(screen.getByRole("button", { name: "Money" }));

    expect(screen.getByRole("heading", { name: "Money Flow" })).toBeInTheDocument();
    expect(screen.getByText("Загрузка economics...")).toBeInTheDocument();
  });

  it("loads economics snapshot and renders money summary, roots, series, and gaps", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (input.toString() === "/api/economics") {
        return jsonResponse(economicsSnapshot);
      }

      return jsonResponse({ error: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.pushState({}, "", "/economics");

    render(<App />);

    expect(await screen.findByText("GET /economics")).toBeInTheDocument();
    expect(screen.getAllByText("$1500.000000").length).toBeGreaterThan(0);
    expect(screen.getByText("$5.000000")).toBeInTheDocument();
    expect(screen.getAllByText("$1495.000000").length).toBeGreaterThan(0);
    expect(screen.getByText("TASK-10")).toBeInTheDocument();
    expect(screen.getAllByText("missing").length).toBeGreaterThan(0);
    expect(screen.getByText("2026-04-28")).toBeInTheDocument();
    expect(screen.getByText("infra_cost")).toBeInTheDocument();
    expect(screen.getByText("retry_waste")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/economics");
  });

  it("generates mock revenue through the frontend api path and reloads economics", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input.toString();
      if (url === "/api/economics" && !init) {
        return jsonResponse(economicsSnapshot);
      }
      if (url === "/api/economics/mock-revenue" && init?.method === "POST") {
        return jsonResponse({
          created_count: 1,
          updated_count: 0,
          created_root_task_ids: [11],
          updated_root_task_ids: []
        });
      }

      return jsonResponse({ error: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.pushState({}, "", "/economics");

    render(<App />);

    await screen.findByText("GET /economics");
    await userEvent.click(screen.getByRole("button", { name: "Mock revenue" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/economics/mock-revenue",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({})
        })
      )
    );
    expect(await screen.findByText("mock revenue: +1 / updated 0")).toBeInTheDocument();
  });

  it("shows backend errors while loading economics", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "Economics unavailable" }, 500)));
    window.history.pushState({}, "", "/economics");

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Economics unavailable");
  });

  it("opens money v2 from the topbar and shows loading state", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));

    render(<App />);

    await userEvent.click(screen.getByRole("button", { name: "Money v2" }));

    expect(screen.getByText(/heavy-lifting · economics/)).toBeInTheDocument();
    expect(screen.getByText("Загружаю экономику...")).toBeInTheDocument();
  });

  it("loads money v2 from direct URL through the economics API", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (input.toString().startsWith("/api/economics")) {
        return jsonResponse(economicsSnapshot);
      }

      return jsonResponse({ error: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.pushState({}, "", "/economics2");

    render(<App />);

    expect(await screen.findByText("GET /economics")).toBeInTheDocument();
    expect(screen.getByText("$1,495.00")).toBeInTheDocument();
    expect(screen.getByText("TASK-10")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/economics"));
  });

  it("opens retro from the topbar and shows loading state", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));

    render(<App />);

    await userEvent.click(screen.getByRole("button", { name: "Retro" }));

    expect(screen.getByText(/ретроспектива/)).toBeInTheDocument();
    expect(screen.getByText("Загружаю боль системы...")).toBeInTheDocument();
  });

  it("loads retro tags, selects a tag, and keeps composer local-only", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = input.toString();
      if (url === "/api/retro/tags") {
        return jsonResponse({ tags: retroTags });
      }
      if (url === "/api/retro/entries?tag=acceptance-missing&limit=10") {
        return jsonResponse({ entries: retroEntries });
      }

      return jsonResponse({ error: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.pushState({}, "", "/retro");

    render(<App />);

    const tagButton = await screen.findByRole("button", {
      name: "acceptance-missing: 8 entries, severity: error"
    });
    expect(tagButton).toHaveClass("rt-sev-error");
    expect(screen.getByRole("button", { name: "slow-ci: 3 entries, severity: warning" }))
      .toHaveClass("rt-sev-warning");
    expect(within(screen.getByLabelText("Pain tag cloud")).getByRole("list"))
      .toBeInTheDocument();

    await userEvent.click(tagButton);

    expect(await screen.findByText("Acceptance criteria were missing before implementation."))
      .toBeInTheDocument();
    expect(screen.getByText(/Ask for concrete acceptance criteria before coding\./))
      .toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/retro/tags");
    expect(fetchMock).toHaveBeenCalledWith("/api/retro/entries?tag=acceptance-missing&limit=10");

    const composer = screen.getByPlaceholderText(
      'Когда встречается "acceptance-missing", агент должен...'
    );
    await userEvent.type(composer, "stop and ask for acceptance criteria");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить локально" }));

    expect(screen.getByText("Черновик сохранен локально")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows explicit empty retro state", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ tags: [] })));
    window.history.pushState({}, "", "/retro");

    render(<App />);

    expect(await screen.findByText("Нет данных. Агенты пока не жаловались."))
      .toBeInTheDocument();
  });

  it("shows retro tag and entry loading errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ error: "Retro tags unavailable" }, 500))
    );
    window.history.pushState({}, "", "/retro");

    const { unmount } = render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Retro tags unavailable");
    unmount();

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = input.toString();
      if (url === "/api/retro/tags") {
        return jsonResponse({ tags: retroTags });
      }
      if (url === "/api/retro/entries?tag=acceptance-missing&limit=10") {
        return jsonResponse({ error: "Retro entries unavailable" }, 500);
      }

      return jsonResponse({ error: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await userEvent.click(
      await screen.findByRole("button", {
        name: "acceptance-missing: 8 entries, severity: error"
      })
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Retro entries unavailable");
    expect(screen.getByText("Нет записей")).toBeInTheDocument();
  });

  it("loads prompts, switches selection, and saves edited content", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input.toString();

      if (url === "/api/settings" && !init) {
        return jsonResponse({ settings: runtimeSettings });
      }

      if (url === "/api/prompts" && !init) {
        return jsonResponse({ prompts });
      }

      if (url === "/api/prompts/review" && init?.method === "PATCH") {
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

    await userEvent.click(await screen.findByRole("tab", { name: "Промты" }));
    const editor = await screen.findByLabelText("Content");
    expect(editor).toHaveValue("DEV prompt");

    await userEvent.click(screen.getByRole("button", { name: /review/ }));
    expect(screen.getByLabelText("Content")).toHaveValue("REVIEW prompt");

    await userEvent.clear(screen.getByLabelText("Content"));
    await userEvent.type(screen.getByLabelText("Content"), "Updated REVIEW prompt");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/prompts/review",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ content: "Updated REVIEW prompt" })
        })
      )
    );
    expect(await screen.findByText("Сохранено")).toBeInTheDocument();
  });

  it("keeps prompt editor usable when runtime settings return an HTML error", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = input.toString();

      if (url === "/api/settings") {
        return htmlResponse("<html><body>Internal Server Error</body></html>", 500);
      }

      if (url === "/api/prompts") {
        return jsonResponse({ prompts });
      }

      return jsonResponse({ error: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.pushState({}, "", "/settings");

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Runtime settings: Backend request failed (500 Internal Server Error)"
    );

    await userEvent.click(screen.getByRole("tab", { name: "Промты" }));

    expect(await screen.findByLabelText("Content")).toHaveValue("DEV prompt");
    expect(screen.getByRole("button", { name: /review/ })).toBeInTheDocument();
  });

  it("loads runtime settings and saves edited values", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input.toString();

      if (url === "/api/settings" && !init) {
        return jsonResponse({ settings: runtimeSettings });
      }

      if (url === "/api/prompts" && !init) {
        return jsonResponse({ prompts });
      }

      if (url === "/api/settings/tracker_fetch_limit" && init?.method === "PATCH") {
        return jsonResponse({
          setting: {
            ...runtimeSettings[0],
            value: "25"
          }
        });
      }

      return jsonResponse({ error: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.pushState({}, "", "/settings");

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Runtime settings" })).toBeInTheDocument();
    expect(screen.getByText("tracker_fetch_limit")).toBeInTheDocument();
    const fetchLimitInput = screen.getByDisplayValue("100");

    await userEvent.clear(fetchLimitInput);
    await userEvent.type(fetchLimitInput, "25");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/tracker_fetch_limit",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ value: "25" })
        })
      )
    );
    expect(await screen.findByText(/Перезапустите процессы/)).toBeInTheDocument();
  });

  it("shows backend errors while loading prompts", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "Backend unavailable" }, 500)));
    window.history.pushState({}, "", "/settings");

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unavailable");
  });
});

function factoryStation(
  name: string,
  overrides: Partial<TestFactoryStation>
) {
  return {
    name,
    counts_by_status: { new: 0, processing: 0, done: 0, failed: 0 },
    total_count: 0,
    wip_count: 0,
    queue_count: 0,
    active_count: 0,
    failed_count: 0,
    oldest_queue_age_seconds: null,
    oldest_active_age_seconds: null,
    ...overrides
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json"
    }
  });
}

function htmlResponse(body: string, status: number): Response {
  return new Response(body, {
    status,
    statusText: "Internal Server Error",
    headers: {
      "Content-Type": "text/html"
    }
  });
}

function mockReducedMotion(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn()
    }))
  );
}
