# Deploy на VPS через GHCR

Документ описывает production-деплой `heavy-lifting` на один VPS через GitHub Actions, GHCR и Docker Compose.

## Требования к VPS

- Linux-хост с Docker Engine и Docker Compose plugin (`docker compose`).
- Пользователь для деплоя, например `heavy-lifting`, с правом запускать Docker.
- Рабочий каталог приложения: `/opt/heavy-lifting`.
- Файл `/opt/heavy-lifting/.env.production` с production-переменными.
- Закрытый внешний доступ к Postgres: production compose не публикует порт `5432`.

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

GitHub Actions публикует image в:

```text
ghcr.io/podlodka-ai-club/heavy-lifting
```

На VPS нужен GitHub PAT с правом `read:packages`, чтобы Docker мог выполнить pull из GHCR:

```bash
echo '<github-pat-with-read-packages>' | docker login ghcr.io -u '<github-username>' --password-stdin
```

## `.env.production`

Создайте `/opt/heavy-lifting/.env.production` без реальных секретов в репозитории. Минимальный шаблон:

```dotenv
APP_IMAGE=ghcr.io/podlodka-ai-club/heavy-lifting:master
APP_PORT=8000

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

`APP_PORT` задает внешний порт VPS для API. Если переменная не задана, production compose и deploy healthcheck используют `8000`. Внутри контейнера API остается на `0.0.0.0:8000`.

## Штатный deploy

Workflow запускается на `push` в `master` и вручную через `workflow_dispatch`.

Порядок действий:

1. Выполняет `make lint`, `make typecheck`, `make test`.
2. Логинится в `ghcr.io` через `GITHUB_TOKEN`.
3. Собирает и публикует image с тегами `master` и `sha-<commit>`.
4. Копирует `docker-compose.prod.yml` в `VPS_APP_DIR`.
5. На VPS выполняет:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml pull
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm bootstrap
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --remove-orphans

APP_PORT=8000
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    APP_PORT=*)
      APP_PORT="${line#APP_PORT=}"
      APP_PORT="${APP_PORT%\"}"
      APP_PORT="${APP_PORT#\"}"
      APP_PORT="${APP_PORT%\'}"
      APP_PORT="${APP_PORT#\'}"
      APP_PORT="${APP_PORT:-8000}"
      break
      ;;
  esac
done < .env.production

healthcheck_url="http://127.0.0.1:${APP_PORT}/health"
ready=0
attempt=1
while [ "$attempt" -le 30 ]; do
  echo "Checking API readiness (${attempt}/30): ${healthcheck_url}"
  if curl -fsS "$healthcheck_url"; then
    ready=1
    break
  fi
  sleep 2
  attempt=$((attempt + 1))
done

if [ "$ready" -ne 1 ]; then
  echo "API did not become ready before timeout" >&2
  docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 api >&2 || true
  exit 1
fi
```

Healthcheck URL снаружи VPS зависит от `APP_PORT` из `.env.production`; если он не задан, используется порт `8000`:

```text
http://<vps-host>:<APP_PORT-or-8000>/health
```

Риск: plain HTTP на внешнем `APP_PORT` не дает TLS и может открыть API всему интернету. Для MVP это допустимо только при осознанном сетевом ограничении. Минимум - firewall allowlist на доверенные IP; лучше - reverse proxy с TLS и закрытый direct access к опубликованному порту.

## Rollback

Rollback выполняется сменой `APP_IMAGE` на нужный immutable tag:

```bash
cd /opt/heavy-lifting
APP_IMAGE=ghcr.io/podlodka-ai-club/heavy-lifting:sha-<commit> \
  docker compose --env-file .env.production -f docker-compose.prod.yml pull
APP_IMAGE=ghcr.io/podlodka-ai-club/heavy-lifting:sha-<commit> \
  docker compose --env-file .env.production -f docker-compose.prod.yml up -d --remove-orphans

APP_PORT=8000
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    APP_PORT=*)
      APP_PORT="${line#APP_PORT=}"
      APP_PORT="${APP_PORT%\"}"
      APP_PORT="${APP_PORT#\"}"
      APP_PORT="${APP_PORT%\'}"
      APP_PORT="${APP_PORT#\'}"
      APP_PORT="${APP_PORT:-8000}"
      break
      ;;
  esac
done < .env.production

curl -fsS "http://127.0.0.1:${APP_PORT}/health"
```

Одиночный `curl` здесь является ручной приемкой после rollback. Штатный deploy использует bounded readiness wait, показанный выше.

Если rollback требует миграции схемы назад, это отдельная операция. Текущий MVP bootstrap рассчитан на подготовку текущей схемы, а не на downgrade.
