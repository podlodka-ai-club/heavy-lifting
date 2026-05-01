# Deploy на VPS через GHCR

Документ описывает production-деплой `heavy-lifting` на один VPS через GitHub Actions, GHCR и Docker Compose.

## Требования к VPS

- Linux-хост с Docker Engine и Docker Compose plugin (`docker compose`).
- Пользователь для деплоя, например `heavy-lifting`, с правом запускать Docker.
- Рабочий каталог приложения: `/opt/heavy-lifting`.
- Файл `/opt/heavy-lifting/.env.production` с production-переменными.
- Открытый внешний HTTP-порт для frontend, по умолчанию `80`.
- Закрытый внешний доступ к Postgres и API: production compose не публикует порты `5432` и `8000`.

Каталог готовится один раз:

```bash
sudo mkdir -p /opt/heavy-lifting
sudo chown heavy-lifting:heavy-lifting /opt/heavy-lifting
```

Если пользователь не входит в группу `docker`, деплой будет падать на командах `docker compose`. Добавьте пользователя в группу и перелогиньте SSH-сессию:

```bash
sudo usermod -aG docker heavy-lifting
```

## SSH-доступ из GitHub Actions

Одного добавления SSH key в GitHub недостаточно. Нужны обе стороны:

- private key кладется в GitHub Secret `VPS_SSH_PRIVATE_KEY`;
- public key добавляется на VPS в `/home/heavy-lifting/.ssh/authorized_keys`.

Также добавьте known hosts запись VPS в secret `VPS_SSH_KNOWN_HOSTS`. Получить ее можно локально:

```bash
ssh-keyscan -p 22 example.com
```

## GitHub Secrets

Workflow `.github/workflows/deploy.yml` ожидает secrets:

- `VPS_HOST` - hostname или IP VPS;
- `VPS_USER` - deploy user, например `heavy-lifting`;
- `VPS_PORT` - SSH-порт, обычно `22`;
- `VPS_SSH_PRIVATE_KEY` - private key для подключения к VPS;
- `VPS_SSH_KNOWN_HOSTS` - known hosts запись VPS;
- `VPS_APP_DIR` - каталог приложения, обычно `/opt/heavy-lifting`.

Runtime-секреты приложения не передаются через GitHub Actions и не запекаются в image. Они должны лежать на VPS в `.env.production`.

## GHCR на VPS

GitHub Actions публикует images в:

```text
ghcr.io/podlodka-ai-club/heavy-lifting
ghcr.io/podlodka-ai-club/heavy-lifting-frontend
```

На VPS нужен GitHub PAT с правом `read:packages`, чтобы Docker мог выполнить pull обоих packages из GHCR:

```bash
echo '<github-pat-with-read-packages>' | docker login ghcr.io -u '<github-username>' --password-stdin
```

## `.env.production`

Создайте `/opt/heavy-lifting/.env.production` без реальных секретов в репозитории. Минимальный шаблон:

```dotenv
APP_IMAGE=ghcr.io/podlodka-ai-club/heavy-lifting:master
FRONTEND_IMAGE=ghcr.io/podlodka-ai-club/heavy-lifting-frontend:master
FRONTEND_PORT=80

FRONTEND_BASIC_AUTH_USERNAME=heavy
FRONTEND_BASIC_AUTH_PASSWORD_HASH='$2a$14$replace-with-caddy-hash'
API_BASIC_AUTH_USERNAME=heavy
API_BASIC_AUTH_PASSWORD=lifting

POSTGRES_DB=heavy_lifting
POSTGRES_USER=heavy_lifting
POSTGRES_PASSWORD=replace-with-strong-password
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
DATABASE_URL=postgresql://heavy_lifting:replace-with-strong-password@postgres:5432/heavy_lifting

WORKSPACE_ROOT=/workspace/repos
WEB_CONCURRENCY=2
GUNICORN_TIMEOUT=120
```

`APP_IMAGE` из файла нужен для ручных команд и rollback. Во время штатного GitHub Actions deploy workflow передает `APP_IMAGE=ghcr.io/podlodka-ai-club/heavy-lifting:sha-<commit>` явно, чтобы поднять ровно собранный commit.

`FRONTEND_IMAGE` из файла нужен для ручных команд и rollback. Во время штатного GitHub Actions deploy workflow передает `FRONTEND_IMAGE=ghcr.io/podlodka-ai-club/heavy-lifting-frontend:sha-<commit>` явно.

`FRONTEND_PORT` задает внешний HTTP-порт VPS для frontend и `/api/*` reverse proxy. Если переменная не задана, production compose и deploy healthcheck используют `80`. Внутри compose backend остается доступен только как `api:8000`; direct `http://<vps-host>:8000/*` больше не публикуется.

`FRONTEND_BASIC_AUTH_USERNAME` и `FRONTEND_BASIC_AUTH_PASSWORD_HASH` обязательны для production frontend: Caddyfile всегда включает Basic Auth на весь сайт, включая `/api/health`. Отсутствие любой из этих переменных является ошибкой deploy до rollout. В hash кладется результат `caddy hash-password`, а не plaintext:

```bash
docker run --rm caddy:2.10-alpine caddy hash-password --plaintext '<frontend-password>'
```

Значение `FRONTEND_BASIC_AUTH_PASSWORD_HASH` в `.env.production` нужно брать в одинарные кавычки, потому что bcrypt hash содержит `$`, а Docker Compose интерпретирует `$...` как подстановку переменных.

`API_BASIC_AUTH_USERNAME` и `API_BASIC_AUTH_PASSWORD` обязательны для текущего production-контракта shared Basic Auth. Caddy проксирует `/api/*` в `api:8000` со strip префикса `/api` и пропускает `Authorization` header к backend.

MVP-контракт Basic Auth: backend API Basic Auth должен использовать тот же plaintext username/password, что и frontend Basic Auth. `FRONTEND_BASIC_AUTH_USERNAME` должен совпадать с `API_BASIC_AUTH_USERNAME`, а `FRONTEND_BASIC_AUTH_PASSWORD_HASH` должен быть hash от того же plaintext password, который лежит в `API_BASIC_AUTH_PASSWORD`. Deploy readiness проверяет `/api/health` через `--user API_BASIC_AUTH_USERNAME:API_BASIC_AUTH_PASSWORD`, но не может проверить hash против plaintext напрямую, поэтому это операционная обязанность того, кто готовит `.env.production`; ошибка здесь приведет к тому, что browser-запросы к `/api/*` пройдут только один из двух guard.

Публичные URL после deploy:

```text
http://<vps-host-or-domain>/        -> frontend
http://<vps-host-or-domain>/api/*   -> backend через frontend reverse proxy
```

## Штатный deploy

Workflow запускается на `push` в `master` и вручную через `workflow_dispatch`.

Порядок действий:

1. Выполняет `make lint`, `make typecheck`, `make test`.
2. Выполняет frontend-проверки: `make frontend-install`, `make frontend-test`, `make frontend-build`.
3. Логинится в `ghcr.io` через `GITHUB_TOKEN`.
4. Собирает и публикует backend/frontend images с тегами `master` и `sha-<commit>`.
5. Копирует `docker-compose.prod.yml` в `VPS_APP_DIR`.
6. На VPS выполняет:

```bash
read_env_value() {
  local env_key="$1"
  local default_value="${2:-}"
  local env_line
  local env_value="$default_value"

  while IFS= read -r env_line || [ -n "$env_line" ]; do
    case "$env_line" in
      "$env_key="*)
        env_value="${env_line#"$env_key="}"
        env_value="${env_value%\"}"
        env_value="${env_value#\"}"
        env_value="${env_value%\'}"
        env_value="${env_value#\'}"
        env_value="${env_value:-$default_value}"
        break
        ;;
    esac
  done < .env.production

  printf '%s' "$env_value"
}

FRONTEND_PORT="$(read_env_value FRONTEND_PORT 80)"
frontend_basic_auth_username="$(read_env_value FRONTEND_BASIC_AUTH_USERNAME)"
frontend_basic_auth_password_hash="$(read_env_value FRONTEND_BASIC_AUTH_PASSWORD_HASH)"
api_basic_auth_username="$(read_env_value API_BASIC_AUTH_USERNAME)"
api_basic_auth_password="$(read_env_value API_BASIC_AUTH_PASSWORD)"

if [ -z "$frontend_basic_auth_username" ] || [ -z "$frontend_basic_auth_password_hash" ]; then
  echo "FRONTEND_BASIC_AUTH_USERNAME and FRONTEND_BASIC_AUTH_PASSWORD_HASH are required for production frontend Basic Auth" >&2
  exit 1
fi
if [ -z "$api_basic_auth_username" ] || [ -z "$api_basic_auth_password" ]; then
  echo "API_BASIC_AUTH_USERNAME and API_BASIC_AUTH_PASSWORD are required for the MVP shared Basic Auth contract" >&2
  exit 1
fi
if [ "$frontend_basic_auth_username" != "$api_basic_auth_username" ]; then
  echo "FRONTEND_BASIC_AUTH_USERNAME must match API_BASIC_AUTH_USERNAME for the MVP shared Basic Auth contract" >&2
  exit 1
fi

docker compose --env-file .env.production -f docker-compose.prod.yml pull
docker compose --env-file .env.production -f docker-compose.prod.yml run --interactive=false -T --rm bootstrap
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --remove-orphans

healthcheck_curl_args=(-fsS --user "${api_basic_auth_username}:${api_basic_auth_password}")
healthcheck_url="http://127.0.0.1:${FRONTEND_PORT}/api/health"
ready=0
attempt=1
while [ "$attempt" -le 30 ]; do
  echo "Checking frontend proxy readiness (${attempt}/30): ${healthcheck_url}"
  if curl "${healthcheck_curl_args[@]}" "$healthcheck_url"; then
    ready=1
    break
  fi
  sleep 2
  attempt=$((attempt + 1))
done

if [ "$ready" -ne 1 ]; then
  echo "Frontend proxy did not become ready before timeout" >&2
  docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 frontend >&2 || true
  docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 api >&2 || true
  exit 1
fi
```

Healthcheck URL снаружи VPS зависит от `FRONTEND_PORT` из `.env.production`; если он не задан, используется порт `80`:

```text
http://<vps-host>:<FRONTEND_PORT-or-80>/api/health
```

Ручные проверки `/api/health` должны передавать `API_BASIC_AUTH_USERNAME` и `API_BASIC_AUTH_PASSWORD`; эти plaintext credentials должны соответствовать username и password, из которого получен `FRONTEND_BASIC_AUTH_PASSWORD_HASH`. Эти credentials не печатаются штатным deploy workflow:

```bash
curl -fsS --user '<API_BASIC_AUTH_USERNAME>:<API_BASIC_AUTH_PASSWORD>' \
  "http://<vps-host>:<FRONTEND_PORT-or-80>/api/health"
```

Риск: Basic Auth поверх plain HTTP на внешнем `FRONTEND_PORT` не дает TLS, поэтому логин и пароль видны на сетевом пути. Это слабый MVP guard, а не полноценная защита. Минимум - firewall allowlist на доверенные IP; лучше - TLS и закрытый direct access ко всем внутренним сервисам.

## Rollback

Rollback выполняется сменой `APP_IMAGE` и `FRONTEND_IMAGE` на нужные immutable tags:

```bash
cd /opt/heavy-lifting
APP_IMAGE=ghcr.io/podlodka-ai-club/heavy-lifting:sha-<commit> \
FRONTEND_IMAGE=ghcr.io/podlodka-ai-club/heavy-lifting-frontend:sha-<commit> \
  docker compose --env-file .env.production -f docker-compose.prod.yml pull
APP_IMAGE=ghcr.io/podlodka-ai-club/heavy-lifting:sha-<commit> \
FRONTEND_IMAGE=ghcr.io/podlodka-ai-club/heavy-lifting-frontend:sha-<commit> \
  docker compose --env-file .env.production -f docker-compose.prod.yml up -d --remove-orphans

read_env_value() {
  local env_key="$1"
  local default_value="${2:-}"
  local env_line
  local env_value="$default_value"

  while IFS= read -r env_line || [ -n "$env_line" ]; do
    case "$env_line" in
      "$env_key="*)
        env_value="${env_line#"$env_key="}"
        env_value="${env_value%\"}"
        env_value="${env_value#\"}"
        env_value="${env_value%\'}"
        env_value="${env_value#\'}"
        env_value="${env_value:-$default_value}"
        break
        ;;
    esac
  done < .env.production

  printf '%s' "$env_value"
}

FRONTEND_PORT="$(read_env_value FRONTEND_PORT 80)"
frontend_basic_auth_username="$(read_env_value FRONTEND_BASIC_AUTH_USERNAME)"
frontend_basic_auth_password_hash="$(read_env_value FRONTEND_BASIC_AUTH_PASSWORD_HASH)"
api_basic_auth_username="$(read_env_value API_BASIC_AUTH_USERNAME)"
api_basic_auth_password="$(read_env_value API_BASIC_AUTH_PASSWORD)"

if [ -z "$frontend_basic_auth_username" ] || [ -z "$frontend_basic_auth_password_hash" ]; then
  echo "FRONTEND_BASIC_AUTH_USERNAME and FRONTEND_BASIC_AUTH_PASSWORD_HASH are required for production frontend Basic Auth" >&2
  exit 1
fi
if [ -z "$api_basic_auth_username" ] || [ -z "$api_basic_auth_password" ]; then
  echo "API_BASIC_AUTH_USERNAME and API_BASIC_AUTH_PASSWORD are required for the MVP shared Basic Auth contract" >&2
  exit 1
fi
if [ "$frontend_basic_auth_username" != "$api_basic_auth_username" ]; then
  echo "FRONTEND_BASIC_AUTH_USERNAME must match API_BASIC_AUTH_USERNAME for the MVP shared Basic Auth contract" >&2
  exit 1
fi

healthcheck_curl_args=(-fsS --user "${api_basic_auth_username}:${api_basic_auth_password}")
curl "${healthcheck_curl_args[@]}" "http://127.0.0.1:${FRONTEND_PORT}/api/health"
```

Одиночный `curl` здесь является ручной приемкой после rollback. Штатный deploy использует bounded readiness wait, показанный выше. Readiness и rollback используют `API_BASIC_AUTH_USERNAME`/`API_BASIC_AUTH_PASSWORD` и требуют совпадения username с `FRONTEND_BASIC_AUTH_USERNAME`; hash должен быть получен из того же plaintext password.

Если rollback требует миграции схемы назад, это отдельная операция. Текущий MVP bootstrap рассчитан на подготовку текущей схемы, а не на downgrade.
