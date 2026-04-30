import { FormEvent, useEffect, useMemo, useState } from "react";

import { listPrompts, Prompt, updatePrompt } from "../../api";

type LoadState = "idle" | "loading" | "loaded" | "error";
type SaveState = "idle" | "saving" | "saved" | "error";

export function SettingsPage() {
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
