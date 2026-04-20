FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    WORKSPACE_ROOT=/workspace/repos

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY . /app

RUN mkdir -p "$WORKSPACE_ROOT" && uv sync --frozen --no-dev

CMD ["sh", "-c", "uv run heavy-lifting-bootstrap-db && exec uv run flask --app backend.api.app:create_app run --host 0.0.0.0 --port 8000"]
