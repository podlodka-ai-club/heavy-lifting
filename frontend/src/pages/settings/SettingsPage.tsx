import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  listPrompts,
  listRuntimeSettings,
  Prompt,
  RuntimeSetting,
  updatePrompt,
  updateRuntimeSetting
} from "../../api";

type LoadState = "idle" | "loading" | "loaded" | "error";
type SaveState = "idle" | "saving" | "saved" | "error";
type SettingsTab = "runtime" | "prompts";

export function SettingsPage() {
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
