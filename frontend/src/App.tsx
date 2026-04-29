import { FormEvent, useEffect, useMemo, useState } from "react";

import { getSettings, updateSettings } from "./api";
import type { SettingsResponse } from "./types";

function App() {
  const isSettingsPage = window.location.pathname.startsWith("/settings");
  return isSettingsPage ? <SettingsPage /> : <HomePage />;
}

function HomePage() {
  return (
    <main className="shell home">
      <section className="home-panel">
        <p className="kicker">MVP backend orchestrator</p>
        <h1>Heacy lifting</h1>
        <a className="primary-link" href="/settings">
          Settings
        </a>
      </section>
    </main>
  );
}

function SettingsPage() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [status, setStatus] = useState("Loading");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getSettings()
      .then((payload) => {
        setSettings(payload);
        setPrompts(Object.fromEntries(payload.agents.map((agent) => [agent.name, agent.prompt])));
        setStatus("");
      })
      .catch((error: unknown) => {
        setStatus(error instanceof Error ? error.message : "Failed to load settings");
      });
  }, []);

  const apiKeyStatus = useMemo(() => {
    if (!settings) {
      return "unknown";
    }
    return settings.api_key.configured ? settings.api_key.source : "not configured";
  }, [settings]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setStatus("");

    try {
      const payload = await updateSettings({
        prompts,
        ...(clearApiKey ? { api_key: null } : {}),
        ...(!clearApiKey && apiKey.trim() ? { api_key: apiKey.trim() } : {})
      });
      setSettings(payload);
      setPrompts(Object.fromEntries(payload.agents.map((agent) => [agent.name, agent.prompt])));
      setApiKey("");
      setClearApiKey(false);
      setStatus("Saved");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="shell settings-shell">
      <header className="topbar">
        <a className="back-link" href="/">
          Heavy Lifting
        </a>
        <span>Settings</span>
      </header>

      <form className="settings-layout" onSubmit={onSubmit}>
        <aside className="settings-sidebar">
          <label className="field">
            <span>API key</span>
            <input
              type="password"
              value={apiKey}
              placeholder={settings?.api_key.configured ? "Saved key" : "New key"}
              onChange={(event) => {
                setApiKey(event.target.value);
                if (event.target.value) {
                  setClearApiKey(false);
                }
              }}
            />
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={clearApiKey}
              onChange={(event) => setClearApiKey(event.target.checked)}
            />
            <span>Clear key</span>
          </label>
          <dl className="metadata">
            <div>
              <dt>Status</dt>
              <dd>{apiKeyStatus}</dd>
            </div>
            <div>
              <dt>Env</dt>
              <dd>{settings?.api_key.env_var ?? "none"}</dd>
            </div>
          </dl>
          <button type="submit" disabled={saving || !settings}>
            {saving ? "Saving" : "Save"}
          </button>
          {status ? <p className="status">{status}</p> : null}
        </aside>

        <section className="prompt-list" aria-label="Agent prompts">
          {settings?.agents.map((agent) => (
            <label className="prompt-editor" key={agent.name}>
              <span>
                {agent.name}
                <small>{agent.source}</small>
              </span>
              <textarea
                value={prompts[agent.name] ?? ""}
                onChange={(event) =>
                  setPrompts((current) => ({
                    ...current,
                    [agent.name]: event.target.value
                  }))
                }
              />
            </label>
          ))}
        </section>
      </form>
    </main>
  );
}

export default App;
