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

describe("App", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/");
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
    expect(screen.getByRole("button", { name: "Money" })).toBeInTheDocument();
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

    const executeStation = screen.getByLabelText("execute station");
    expect(within(executeStation).getByText("BOTTLENECK")).toBeInTheDocument();
    expect(within(executeStation).getByText("1h 1m")).toBeInTheDocument();
    expect(within(executeStation).getByText("3m")).toBeInTheDocument();
    expect(within(executeStation).getByText("failed 1")).toBeInTheDocument();

    const feedbackStation = screen.getByLabelText("pr feedback station");
    const zeroWipMeter = within(feedbackStation).getByLabelText("pr feedback WIP 0");
    expect(zeroWipMeter.firstElementChild).toHaveStyle({ minWidth: "0", width: "0%" });

    expect(screen.getByText("Не показываем то, чего нет в API")).toBeInTheDocument();
    expect(screen.getByText("transition_history")).toBeInTheDocument();
    expect(screen.getByText("worker_capacity")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/factory");
  });

  it("shows backend errors while loading factory", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "Factory unavailable" }, 500)));
    window.history.pushState({}, "", "/factory");

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Factory unavailable");
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

  it("loads prompts, switches selection, and saves edited content", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input.toString();

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
