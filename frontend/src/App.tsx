import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  FactorySnapshot,
  FactoryStation,
  getFactorySnapshot,
  listRuntimeSettings,
  listPrompts,
  Prompt,
  RuntimeSetting,
  updateRuntimeSetting,
  updatePrompt
} from "./api";

type Route = "/" | "/factory" | "/settings";
type LoadState = "idle" | "loading" | "loaded" | "error";
type SaveState = "idle" | "saving" | "saved" | "error";
type SettingsTab = "runtime" | "prompts";

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
  if (pathname === "/settings" || pathname === "/factory") {
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

function FactoryPage() {
  const [snapshot, setSnapshot] = useState<FactorySnapshot | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [error, setError] = useState<string>("");
  const prefersReducedMotion = usePrefersReducedMotion();

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
            <FactoryRoutes
              prefersReducedMotion={prefersReducedMotion}
              stations={snapshot.stations}
            />

            <div className="orchestrator-node">
              <div className="orchestrator-core" aria-hidden="true">
                <span />
                <span />
              </div>
              <span className="mono-label">ORCHESTRATOR</span>
              <strong>handoff control</strong>
            </div>

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

function FactoryRoutes({
  stations,
  prefersReducedMotion
}: {
  stations: FactoryStation[];
  prefersReducedMotion: boolean;
}) {
  const stationsWithWip = new Set(
    stations.filter((station) => station.wip_count > 0).map((station) => station.name)
  );

  return (
    <svg
      className="factory-routes"
      viewBox="0 0 1000 620"
      role="img"
      aria-label="Factory handoff routes"
    >
      <path className="handoff-route route-fetch" d="M500 108 C410 168 285 238 178 334" />
      <path className="handoff-route route-execute" d="M500 108 C470 222 426 316 358 410" />
      <path className="handoff-route route-pr_feedback" d="M500 108 C574 224 642 316 730 408" />
      <path className="handoff-route route-deliver" d="M500 108 C626 170 746 248 852 342" />

      {stationsWithWip.has("fetch") ? (
        <circle
          className="payload-marker payload-fetch"
          cx={prefersReducedMotion ? 178 : undefined}
          cy={prefersReducedMotion ? 334 : undefined}
          r="8"
          aria-label="fetch payload marker"
        >
          {prefersReducedMotion ? null : (
            <animateMotion dur="9s" repeatCount="indefinite" path="M500 108 C410 168 285 238 178 334" />
          )}
        </circle>
      ) : null}
      {stationsWithWip.has("execute") ? (
        <circle
          className="payload-marker payload-execute"
          cx={prefersReducedMotion ? 358 : undefined}
          cy={prefersReducedMotion ? 410 : undefined}
          r="9"
          aria-label="execute payload marker"
        >
          {prefersReducedMotion ? null : (
            <animateMotion dur="7s" repeatCount="indefinite" path="M500 108 C470 222 426 316 358 410" />
          )}
        </circle>
      ) : null}
      {stationsWithWip.has("pr_feedback") ? (
        <circle
          className="payload-marker payload-pr_feedback"
          cx={prefersReducedMotion ? 730 : undefined}
          cy={prefersReducedMotion ? 408 : undefined}
          r="8"
          aria-label="pr feedback payload marker"
        >
          {prefersReducedMotion ? null : (
            <animateMotion dur="8s" repeatCount="indefinite" path="M500 108 C574 224 642 316 730 408" />
          )}
        </circle>
      ) : null}
      {stationsWithWip.has("deliver") ? (
        <circle
          className="payload-marker payload-deliver"
          cx={prefersReducedMotion ? 852 : undefined}
          cy={prefersReducedMotion ? 342 : undefined}
          r="8"
          aria-label="deliver payload marker"
        >
          {prefersReducedMotion ? null : (
            <animateMotion dur="10s" repeatCount="indefinite" path="M500 108 C626 170 746 248 852 342" />
          )}
        </circle>
      ) : null}
    </svg>
  );
}

function usePrefersReducedMotion(): boolean {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(() =>
    Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches)
  );

  useEffect(() => {
    const mediaQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mediaQuery) {
      return;
    }

    setPrefersReducedMotion(mediaQuery.matches);

    const onChange = (event: MediaQueryListEvent) => {
      setPrefersReducedMotion(event.matches);
    };

    mediaQuery.addEventListener("change", onChange);
    return () => mediaQuery.removeEventListener("change", onChange);
  }, []);

  return prefersReducedMotion;
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
      <div className="station-machine" aria-hidden="true">
        <div className="machine-cube">
          <span className="cube-top" />
          <span className="cube-front" />
          <span className="cube-side" />
        </div>
        <div className="machine-stack">
          {Array.from({ length: Math.min(station.wip_count, 5) }, (_, index) => (
            <span key={index} />
          ))}
        </div>
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
  const [activeTab, setActiveTab] = useState<SettingsTab>("runtime");
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSetting[]>([]);
  const [runtimeDrafts, setRuntimeDrafts] = useState<Record<string, string>>({});
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [selectedKey, setSelectedKey] = useState<string>("");
  const [draftContent, setDraftContent] = useState<string>("");
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let cancelled = false;

    async function loadSettings() {
      setLoadState("loading");
      setError("");

      try {
        const [loadedRuntimeSettings, loadedPrompts] = await Promise.all([
          listRuntimeSettings(),
          listPrompts()
        ]);

        if (cancelled) {
          return;
        }

        setRuntimeSettings(loadedRuntimeSettings);
        setRuntimeDrafts(
          Object.fromEntries(
            loadedRuntimeSettings.map((setting) => [setting.setting_key, setting.value])
          )
        );
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
        setError(loadError instanceof Error ? loadError.message : "Не удалось загрузить настройки");
      }
    }

    void loadSettings();

    return () => {
      cancelled = true;
    };
  }, []);

  const selectedPrompt = useMemo(
    () => prompts.find((prompt) => prompt.prompt_key === selectedKey) ?? null,
    [prompts, selectedKey]
  );
  const hasChanges = Boolean(selectedPrompt && draftContent !== selectedPrompt.content);
  const hasRuntimeChanges = runtimeSettings.some(
    (setting) => runtimeDrafts[setting.setting_key] !== setting.value
  );

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

  async function saveRuntimeSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!hasRuntimeChanges || saveState === "saving") {
      return;
    }

    setSaveState("saving");
    setError("");

    try {
      const changedSettings = runtimeSettings.filter(
        (setting) => runtimeDrafts[setting.setting_key] !== setting.value
      );
      const savedSettings = await Promise.all(
        changedSettings.map((setting) =>
          updateRuntimeSetting(setting.setting_key, runtimeDrafts[setting.setting_key] ?? "")
        )
      );
      const savedByKey = new Map(savedSettings.map((setting) => [setting.setting_key, setting]));
      const nextSettings = runtimeSettings.map(
        (setting) => savedByKey.get(setting.setting_key) ?? setting
      );

      setRuntimeSettings(nextSettings);
      setRuntimeDrafts(
        Object.fromEntries(nextSettings.map((setting) => [setting.setting_key, setting.value]))
      );
      setSaveState("saved");
    } catch (saveError) {
      setSaveState("error");
      setError(saveError instanceof Error ? saveError.message : "Не удалось сохранить настройки");
    }
  }

  return (
    <main className="page">
      <div className="section-heading">
        <p className="eyebrow">Настройки</p>
        <h1>Runtime и промты</h1>
      </div>

      <div className="settings-tabs" role="tablist" aria-label="Разделы настроек">
        <button
          className={activeTab === "runtime" ? "settings-tab active" : "settings-tab"}
          type="button"
          role="tab"
          aria-selected={activeTab === "runtime"}
          onClick={() => {
            setActiveTab("runtime");
            setSaveState("idle");
            setError("");
          }}
        >
          Runtime
        </button>
        <button
          className={activeTab === "prompts" ? "settings-tab active" : "settings-tab"}
          type="button"
          role="tab"
          aria-selected={activeTab === "prompts"}
          onClick={() => {
            setActiveTab("prompts");
            setSaveState("idle");
            setError("");
          }}
        >
          Промты
        </button>
      </div>

      {loadState === "loading" ? <p className="muted">Загрузка...</p> : null}
      {error ? (
        <p className="status-error" role="alert">
          {error}
        </p>
      ) : null}
      {loadState === "loaded" && activeTab === "prompts" && prompts.length === 0 ? (
        <p className="muted">Промты не найдены.</p>
      ) : null}

      {activeTab === "runtime" && runtimeSettings.length > 0 ? (
        <form className="runtime-settings-panel" onSubmit={saveRuntimeSettings}>
          <div className="editor-header">
            <div>
              <h2>Runtime settings</h2>
              <p className="muted">
                Значения сохраняются в БД и применяются после рестарта API и воркеров.
              </p>
            </div>
            <button
              className="primary-button"
              type="submit"
              disabled={!hasRuntimeChanges || saveState === "saving"}
            >
              {saveState === "saving" ? "Сохранение..." : "Сохранить"}
            </button>
          </div>

          <div className="runtime-settings-grid">
            {runtimeSettings.map((setting) => (
              <label className="runtime-setting-row" key={setting.setting_key}>
                <span>
                  <strong>{setting.setting_key}</strong>
                  <small>{setting.description}</small>
                  <small>
                    {setting.env_var} · default {setting.default_value}
                  </small>
                </span>
                <input
                  type={setting.value_type === "int" ? "number" : "text"}
                  min={setting.value_type === "int" ? 1 : undefined}
                  value={runtimeDrafts[setting.setting_key] ?? ""}
                  onChange={(event) => {
                    setRuntimeDrafts((currentDrafts) => ({
                      ...currentDrafts,
                      [setting.setting_key]: event.target.value
                    }));
                    setSaveState("idle");
                  }}
                />
              </label>
            ))}
          </div>
          {saveState === "saved" ? (
            <p className="status-ok">Сохранено. Перезапустите процессы для применения.</p>
          ) : null}
        </form>
      ) : null}

      {activeTab === "prompts" && prompts.length > 0 ? (
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
