.PHONY: install init install-git-hooks clean api worker1 worker2 worker3 demo lint typecheck test bootstrap-db init-db frontend-install frontend-dev frontend-build frontend-test


install: init

init:
	uv sync
	$(MAKE) install-git-hooks

install-git-hooks:
	@mkdir -p .git/hooks
	@install -m 0755 githooks/pre-commit .git/hooks/pre-commit

clean:
	@rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis .nox .tox .eggs build dist htmlcov
	@rm -f .coverage .coverage.* coverage.xml
	@find . -maxdepth 1 -type d -name "*.egg-info" -exec rm -rf {} +
	@for path in src tests; do \
		if [ -d "$$path" ]; then \
			find "$$path" -type d -name __pycache__ -exec rm -rf {} +; \
			find "$$path" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete; \
		fi; \
	done

api:
	uv run flask --app backend.api.app:create_app run --debug --host 0.0.0.0 --port 8000

worker1:
	uv run python -c "from backend.workers.fetch_worker import run; run()"

worker2:
	uv run python -c "from backend.workers.execute_worker import run; run()"

worker3:
	uv run python -c "from backend.workers.deliver_worker import run; run()"

demo:
	uv run heavy-lifting-demo

lint:
	@if [ -d tests ]; then uv run ruff check src/backend tests; else uv run ruff check src/backend; fi

typecheck:
	uv run mypy src/backend

test:
	uv run pytest

bootstrap-db:
	uv run heavy-lifting-bootstrap-db

init-db: bootstrap-db

frontend-install:
	cd frontend && npm ci

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

frontend-test:
	cd frontend && npm test
