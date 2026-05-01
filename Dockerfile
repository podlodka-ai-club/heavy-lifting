FROM node:22-slim AS opencode

RUN npm install -g opencode-ai \
    && opencode --version

FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/podlodka-ai-club/heavy-lifting"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    OPENCODE_DISABLE_AUTOUPDATE=1 \
    WORKSPACE_ROOT=/workspace/repos

WORKDIR /app

COPY --from=opencode /usr/local/bin/node /usr/local/bin/node
COPY --from=opencode /usr/local/lib/node_modules /usr/local/lib/node_modules

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git openssh-client \
    && ln -sf ../lib/node_modules/opencode-ai/bin/opencode /usr/local/bin/opencode \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY . /app

RUN mkdir -p "$WORKSPACE_ROOT" && uv sync --frozen --no-dev

CMD ["sh", "-c", "uv run heavy-lifting-bootstrap-db && exec uv run flask --app backend.api.app:create_app run --host 0.0.0.0 --port 8000"]
