import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  EconomicsSnapshot,
  generateMockRevenue,
  getEconomicsSnapshot,
  FactorySnapshot,
  FactoryStation,
  getFactorySnapshot,
  listPrompts,
  Prompt,
  updatePrompt
} from "./api";

type Route = "/" | "/factory" | "/economics" | "/settings";
type LoadState = "idle" | "loading" | "loaded" | "error";
type SaveState = "idle" | "saving" | "saved" | "error";
type ActionState = "idle" | "running" | "done" | "error";

const stationMeta: Record<
  FactoryStation["name"],
  { label: string; title: string; shortLabel: string }
> = {
  fetch: { label: "FETCH", title: "tracker intake", shortLabel: "fetch" },
  execute: { label: "EXECUTE", title: "triage · runner · workspace", shortLabel: "execute" },
  pr_feedback: { label: "PR_FEEDBACK", title: "review response", shortLabel: "pr feedback" },
  deliver: { label: "DELIVER", title: "tracker delivery", shortLabel: "deliver" }
};

function getRoute(pathname: string): Route {
  if (pathname === "/settings" || pathname === "/factory" || pathname === "/economics") {
    return pathname;
  }

  return "/";
}

export function App() {
  const [route, setRoute] = useState<Route>(() => getRoute(window.location.pathname));

  useEffect(() => {
    const onPopState = () => setRoute(getRoute(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  function navigate(nextRoute: Route) {
    window.history.pushState({}, "", nextRoute);
    setRoute(nextRoute);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand-link" type="button" onClick={() => navigate("/")}>
          heavy-lifting
        </button>
        <nav aria-label="Основная навигация">
          <button
            className={route === "/factory" ? "nav-link active" : "nav-link"}
            type="button"
            onClick={() => navigate("/factory")}
          >
            Factory
          </button>
          <button
            className={route === "/economics" ? "nav-link active" : "nav-link"}
            type="button"
            onClick={() => navigate("/economics")}
          >
            Money
          </button>
          <button
            className={route === "/settings" ? "nav-link active" : "nav-link"}
            type="button"
            onClick={() => navigate("/settings")}
          >
            Настройки
          </button>
        </nav>
      </header>
      {route === "/settings" ? <SettingsPage /> : null}
      {route === "/factory" ? <FactoryPage /> : null}
      {route === "/economics" ? <EconomicsPage /> : null}
      {route === "/" ? <HomePage /> : null}
    </div>
  );
}

function HomePage() {
  return (
    <main className="page page-narrow">
      <p className="eyebrow">MVP orchestrator</p>
      <h1>heavy-lifting</h1>
      <p className="intro">
        Локальная панель для наблюдения за factory flow и редактирования настроек
        backend-оркестратора.
      </p>
    </main>
  );
}

function EconomicsPage() {
  const [snapshot, setSnapshot] = useState<EconomicsSnapshot | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [actionState, setActionState] = useState<ActionState>("idle");
  const [error, setError] = useState<string>("");
  const [actionMessage, setActionMessage] = useState<string>("");

  async function loadEconomics(cancelled: () => boolean = () => false) {
    setLoadState("loading");
    setError("");

    try {
      const loadedSnapshot = await getEconomicsSnapshot();

      if (cancelled()) {
        return;
      }

      setSnapshot(loadedSnapshot);
      setLoadState("loaded");
    } catch (loadError) {
      if (cancelled()) {
        return;
      }

      setLoadState("error");
      setError(loadError instanceof Error ? loadError.message : "Не удалось загрузить economics");
    }
  }

  useEffect(() => {
    let cancelled = false;
    void loadEconomics(() => cancelled);

    return () => {
      cancelled = true;
    };
  }, []);

  async function createMockRevenue() {
    if (actionState === "running") {
      return;
    }

    setActionState("running");
    setActionMessage("");
    setError("");

    try {
      const result = await generateMockRevenue();
      setActionState("done");
      setActionMessage(`mock revenue: +${result.created_count} / updated ${result.updated_count}`);
      await loadEconomics();
    } catch (actionError) {
      setActionState("error");
      setError(
        actionError instanceof Error ? actionError.message : "Не удалось создать mock revenue"
      );
    }
  }

  return (
    <main className="page economics-page">
      <section className="factory-hud" aria-label="Economics summary">
        <div className="hud-panel hud-main">
          <p className="eyebrow">heavy-lifting · economics</p>
          <h1>Money Flow</h1>
          <p className="intro">
            Snapshot закрытых root-задач: revenue, token cost, profit и явные пробелы в
            экономической модели MVP.
          </p>
        </div>
        <div className="hud-panel hud-card">
          <span className="mono-label">Profit</span>
          <strong>{formatMoney(snapshot?.totals.profit_usd ?? "0.000000")}</strong>
          <span className="muted">{snapshot?.totals.closed_roots_count ?? 0} closed roots</span>
        </div>
      </section>

      {loadState === "loading" ? <p className="factory-loading">Загрузка economics...</p> : null}
      {error ? (
        <p className="status-error" role="alert">
          {error}
        </p>
      ) : null}

      {snapshot ? (
        <>
          <section className="factory-telemetry" aria-label="Economics telemetry">
            <span>
              <strong>GET /economics</strong>
            </span>
            <span>generated_at={formatDateTime(snapshot.generated_at)}</span>
            <span>bucket={snapshot.period.bucket}</span>
            <span>missing={snapshot.totals.missing_revenue_count}</span>
            <button
              className="inline-action"
              type="button"
              disabled={actionState === "running"}
              onClick={createMockRevenue}
            >
              {actionState === "running" ? "Generating..." : "Mock revenue"}
            </button>
            {actionMessage ? <span className="status-inline-ok">{actionMessage}</span> : null}
          </section>

          <section className="economics-summary-grid" aria-label="Money summary">
            <Metric label="Revenue" value={formatMoney(snapshot.totals.revenue_usd)} />
            <Metric label="Token cost" value={formatMoney(snapshot.totals.token_cost_usd)} />
            <Metric
              label="Profit"
              tone={snapshot.totals.profit_usd.startsWith("-") ? "bad" : "normal"}
              value={formatMoney(snapshot.totals.profit_usd)}
            />
            <Metric label="Monetized" value={snapshot.totals.monetized_roots_count} />
            <Metric
              label="Missing"
              tone={snapshot.totals.missing_revenue_count > 0 ? "bad" : "normal"}
              value={snapshot.totals.missing_revenue_count}
            />
            <Metric label="Closed" value={snapshot.totals.closed_roots_count} />
          </section>

          <section className="economics-table-panel" aria-label="Economics series">
            <div className="section-heading compact">
              <p className="eyebrow">Series</p>
              <h2>Bucketed money</h2>
            </div>
            <DataTable
              emptyText="No closed roots in this period."
              rows={snapshot.series.map((point) => [
                point.bucket,
                String(point.closed_roots_count),
                String(point.monetized_roots_count),
                formatMoney(point.revenue_usd),
                formatMoney(point.token_cost_usd),
                formatMoney(point.profit_usd)
              ])}
              headers={["bucket", "closed", "monetized", "revenue", "cost", "profit"]}
            />
          </section>

          <section className="economics-table-panel" aria-label="Economics roots">
            <div className="section-heading compact">
              <p className="eyebrow">Roots</p>
              <h2>Closed root tasks</h2>
            </div>
            <DataTable
              emptyText="No closed roots."
              rows={snapshot.roots.map((root) => [
                String(root.root_task_id),
                root.external_task_id ?? "none",
                formatDateTime(root.closed_at),
                root.revenue_usd ? formatMoney(root.revenue_usd) : "missing",
                formatMoney(root.token_cost_usd),
                root.profit_usd ? formatMoney(root.profit_usd) : "missing",
                root.revenue_source ?? "none",
                root.revenue_confidence ?? "none"
              ])}
              headers={[
                "root",
                "external",
                "closed",
                "revenue",
                "cost",
                "profit",
                "source",
                "confidence"
              ]}
            />
          </section>

          <section className="gaps-panel" aria-label="Economics data gaps">
            <div>
              <p className="eyebrow">Data gaps</p>
              <h2>Честные пробелы экономики MVP</h2>
            </div>
            <ul>
              {snapshot.data_gaps.map((gap) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          </section>
        </>
      ) : null}
    </main>
  );
}

function DataTable({
  headers,
  rows,
  emptyText
}: {
  headers: string[];
  rows: string[][];
  emptyText: string;
}) {
  if (rows.length === 0) {
    return <p className="muted">{emptyText}</p>;
  }

  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.join("|")}>
              {row.map((cell, index) => (
                <td key={`${index}:${cell}`}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FactoryPage() {
  const [snapshot, setSnapshot] = useState<FactorySnapshot | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let cancelled = false;

    async function loadFactory() {
      setLoadState("loading");
      setError("");

      try {
        const loadedSnapshot = await getFactorySnapshot();

        if (cancelled) {
          return;
        }

        setSnapshot(loadedSnapshot);
        setLoadState("loaded");
      } catch (loadError) {
        if (cancelled) {
          return;
        }

        setLoadState("error");
        setError(loadError instanceof Error ? loadError.message : "Не удалось загрузить factory");
      }
    }

    void loadFactory();

    return () => {
      cancelled = true;
    };
  }, []);

  const totalWip = snapshot?.stations.reduce((sum, station) => sum + station.wip_count, 0) ?? 0;
  const totalFailed =
    snapshot?.stations.reduce((sum, station) => sum + station.failed_count, 0) ?? 0;
  const totalActive =
    snapshot?.stations.reduce((sum, station) => sum + station.active_count, 0) ?? 0;

  return (
    <main className="page factory-page">
      <section className="factory-hud" aria-label="Factory summary">
        <div className="hud-panel hud-main">
          <p className="eyebrow">heavy-lifting · factory command map</p>
          <h1>Factory Flow</h1>
          <p className="intro">
            Live snapshot из `/factory`: станции, очереди, активная работа, ошибки и честные
            data gaps без синтетических метрик.
          </p>
        </div>
        <div className="hud-panel hud-card">
          <span className="mono-label">Current bottleneck</span>
          <strong>{snapshot?.bottleneck?.station ?? "none"}</strong>
          <span className="muted">
            {snapshot?.bottleneck ? `WIP ${snapshot.bottleneck.wip_count}` : "No WIP"}
          </span>
        </div>
      </section>

      {loadState === "loading" ? <p className="factory-loading">Загрузка factory...</p> : null}
      {error ? (
        <p className="status-error" role="alert">
          {error}
        </p>
      ) : null}

      {snapshot ? (
        <>
          <section className="factory-telemetry" aria-label="Factory telemetry">
            <span>
              <strong>GET /factory</strong>
            </span>
            <span>generated_at={formatDateTime(snapshot.generated_at)}</span>
            <span>wip={totalWip}</span>
            <span>active={totalActive}</span>
            <span>failed={totalFailed}</span>
          </section>

          <section className="factory-map" aria-label="Factory station map">
            <div className="orchestrator-node">
              <span className="mono-label">ORCHESTRATOR</span>
              <strong>handoff control</strong>
            </div>

            <div className="factory-line" aria-hidden="true" />

            <div className="station-grid">
              {snapshot.stations.map((station) => (
                <StationCard
                  isBottleneck={snapshot.bottleneck?.station === station.name}
                  key={station.name}
                  station={station}
                />
              ))}
            </div>
          </section>

          <section className="gaps-panel" aria-label="Data gaps">
            <div>
              <p className="eyebrow">Data gaps</p>
              <h2>Не показываем то, чего нет в API</h2>
            </div>
            <ul>
              {snapshot.data_gaps.map((gap) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          </section>
        </>
      ) : null}
    </main>
  );
}

function StationCard({
  station,
  isBottleneck
}: {
  station: FactoryStation;
  isBottleneck: boolean;
}) {
  const meta = stationMeta[station.name];

  return (
    <article
      className={`station-card station-${station.name}${isBottleneck ? " bottleneck" : ""}`}
      aria-label={`${meta.shortLabel} station`}
    >
      <div className="station-topline">
        <span className="mono-label">{meta.label}</span>
        {isBottleneck ? <span className="hot-badge">BOTTLENECK</span> : null}
      </div>
      <h2>{meta.title}</h2>
      <div className="wip-meter" aria-label={`${meta.shortLabel} WIP ${station.wip_count}`}>
        <span
          style={{
            minWidth: station.wip_count > 0 ? "3px" : "0",
            width: `${Math.min(100, station.wip_count * 12)}%`
          }}
        />
      </div>
      <div className="metric-grid">
        <Metric label="WIP" value={station.wip_count} />
        <Metric label="Queue" value={station.queue_count} />
        <Metric label="Active" value={station.active_count} />
        <Metric label="Failed" tone={station.failed_count > 0 ? "bad" : "normal"} value={station.failed_count} />
        <Metric label="Oldest q" value={formatAge(station.oldest_queue_age_seconds)} />
        <Metric label="Oldest a" value={formatAge(station.oldest_active_age_seconds)} />
      </div>
      <div className="status-strip" aria-label={`${meta.shortLabel} status counts`}>
        <span>new {station.counts_by_status.new}</span>
        <span>processing {station.counts_by_status.processing}</span>
        <span>done {station.counts_by_status.done}</span>
        <span>failed {station.counts_by_status.failed}</span>
        <span>total {station.total_count}</span>
      </div>
    </article>
  );
}

function Metric({
  label,
  value,
  tone = "normal"
}: {
  label: string;
  value: number | string;
  tone?: "normal" | "bad";
}) {
  return (
    <span className="metric">
      <span className="metric-label">{label}</span>
      <strong className={tone === "bad" ? "metric-value bad" : "metric-value"}>{value}</strong>
    </span>
  );
}

function SettingsPage() {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [selectedKey, setSelectedKey] = useState<string>("");
  const [draftContent, setDraftContent] = useState<string>("");
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let cancelled = false;

    async function loadPrompts() {
      setLoadState("loading");
      setError("");

      try {
        const loadedPrompts = await listPrompts();

        if (cancelled) {
          return;
        }

        setPrompts(loadedPrompts);
        setLoadState("loaded");

        const firstPrompt = loadedPrompts[0];
        if (firstPrompt) {
          setSelectedKey(firstPrompt.prompt_key);
          setDraftContent(firstPrompt.content);
        }
      } catch (loadError) {
        if (cancelled) {
          return;
        }

        setLoadState("error");
        setError(loadError instanceof Error ? loadError.message : "Не удалось загрузить промты");
      }
    }

    void loadPrompts();

    return () => {
      cancelled = true;
    };
  }, []);

  const selectedPrompt = useMemo(
    () => prompts.find((prompt) => prompt.prompt_key === selectedKey) ?? null,
    [prompts, selectedKey]
  );
  const hasChanges = Boolean(selectedPrompt && draftContent !== selectedPrompt.content);

  function selectPrompt(promptKey: string) {
    const nextPrompt = prompts.find((prompt) => prompt.prompt_key === promptKey);
    if (!nextPrompt) {
      return;
    }

    setSelectedKey(promptKey);
    setDraftContent(nextPrompt.content);
    setSaveState("idle");
    setError("");
  }

  async function savePrompt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!selectedPrompt || !hasChanges || saveState === "saving") {
      return;
    }

    setSaveState("saving");
    setError("");

    try {
      const savedPrompt = await updatePrompt(selectedPrompt.prompt_key, draftContent);
      setPrompts((currentPrompts) =>
        currentPrompts.map((prompt) =>
          prompt.prompt_key === savedPrompt.prompt_key ? savedPrompt : prompt
        )
      );
      setDraftContent(savedPrompt.content);
      setSaveState("saved");
    } catch (saveError) {
      setSaveState("error");
      setError(saveError instanceof Error ? saveError.message : "Не удалось сохранить промт");
    }
  }

  return (
    <main className="page">
      <div className="section-heading">
        <p className="eyebrow">Настройки</p>
        <h1>Промты агентов</h1>
      </div>

      {loadState === "loading" ? <p className="muted">Загрузка...</p> : null}
      {error ? (
        <p className="status-error" role="alert">
          {error}
        </p>
      ) : null}
      {loadState === "loaded" && prompts.length === 0 ? (
        <p className="muted">Промты не найдены.</p>
      ) : null}

      {prompts.length > 0 ? (
        <div className="settings-layout">
          <aside className="prompt-list" aria-label="Список промтов">
            {prompts.map((prompt) => (
              <button
                className={prompt.prompt_key === selectedKey ? "prompt-item active" : "prompt-item"}
                key={prompt.prompt_key}
                type="button"
                onClick={() => selectPrompt(prompt.prompt_key)}
              >
                <span>{prompt.prompt_key}</span>
                <small>{prompt.source_path}</small>
              </button>
            ))}
          </aside>

          <form className="prompt-editor" onSubmit={savePrompt}>
            <div className="editor-header">
              <div>
                <h2>{selectedPrompt?.prompt_key}</h2>
                <p className="muted">{selectedPrompt?.source_path}</p>
              </div>
              <button
                className="primary-button"
                type="submit"
                disabled={!hasChanges || saveState === "saving"}
              >
                {saveState === "saving" ? "Сохранение..." : "Сохранить"}
              </button>
            </div>

            <label className="field-label" htmlFor="prompt-content">
              Content
            </label>
            <textarea
              id="prompt-content"
              value={draftContent}
              onChange={(event) => {
                setDraftContent(event.target.value);
                setSaveState("idle");
              }}
            />
            {saveState === "saved" ? <p className="status-ok">Сохранено</p> : null}
          </form>
        </div>
      ) : null}
    </main>
  );
}

function formatAge(seconds: number | null): string {
  if (seconds === null) {
    return "none";
  }

  if (seconds < 60) {
    return `${seconds}s`;
  }

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m`;
  }

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes === 0 ? `${hours}h` : `${hours}h ${remainingMinutes}m`;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("ru-RU", {
    dateStyle: "short",
    timeStyle: "medium"
  });
}

function formatMoney(value: string): string {
  return `$${value}`;
}
