.PHONY: install api worker1 worker2 worker3 lint typecheck test bootstrap-db init-db

install:
	uv sync

api:
	uv run flask --app backend.api.app:create_app run --debug --host 0.0.0.0 --port 8000

worker1:
	uv run python -c "from backend.workers.fetch_worker import run; run()"

worker2:
	uv run python -c "from backend.workers.execute_worker import run; run()"

worker3:
	uv run python -c "from backend.workers.deliver_worker import run; run()"

lint:
	@if [ -d tests ]; then uv run ruff check src/backend tests; else uv run ruff check src/backend; fi

typecheck:
	uv run mypy src/backend

test:
	uv run pytest

bootstrap-db:
	uv run python -c "print('Database bootstrap is not implemented yet; target reserved for a future task.')"

init-db: bootstrap-db
