# REST API

Backend exposes a Flask REST API. The machine-readable schema is available at:

```text
GET /openapi.json
```

## Settings

Settings endpoints are MVP runtime settings for the local orchestrator UI.

### `GET /settings`

Returns API key status and effective agent prompts.

Response:

```json
{
  "api_key": {
    "configured": true,
    "source": "runtime",
    "env_var": "OPENAI_API_KEY"
  },
  "agents": [
    {
      "name": "implementer",
      "prompt": "# Implementer\n...",
      "source": "runtime"
    }
  ]
}
```

`api_key.source` is one of:

- `runtime` — key is stored in runtime-local settings JSON;
- `env` — key is available from the process env variable;
- `none` — no key is configured.

The API key value is intentionally not returned.

### `PUT /settings`

Updates runtime API key and agent prompt overrides.

Request:

```json
{
  "api_key": "sk-...",
  "prompts": {
    "implementer": "# Implementer\n..."
  }
}
```

Use `null` or an empty string for `api_key` to clear the runtime key. Omit `api_key` to leave the current key unchanged. `prompts` accepts known agent names from `AGENT_PROMPTS_DIR`; unknown names return `400`.

Response shape is the same as `GET /settings`.

## Runtime Storage

Runtime settings are stored in `RUNTIME_SETTINGS_PATH`, defaulting to:

```text
var/runtime-settings.json
```

The default path is gitignored. Source prompt files in `prompts/agents/*.md` remain tracked defaults; saved prompt changes are stored as runtime overrides in the JSON file.

If the runtime settings file contains invalid JSON, the backend treats it as empty runtime state for reads and CLI API key overrides. A later `PUT /settings` writes a valid replacement file.
