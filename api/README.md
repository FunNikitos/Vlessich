# Vlessich — Backend API (FastAPI)

Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL 16 · Alembic.

## Dev

```bash
cp .env.example .env.dev
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

## Endpoints

| Path                              | Auth        | Назначение                                      |
|-----------------------------------|-------------|-------------------------------------------------|
| `GET /healthz`, `GET /readyz`     | —           | k8s/docker probes                               |
| `GET /metrics`                    | —           | Prometheus                                      |
| `POST /internal/codes/activate`   | HMAC (§11A) | Активация кода (из бота)                        |
| `POST /internal/trials`           | HMAC        | Выдача триала                                   |
| `POST /internal/mtproto/issue`    | HMAC        | Выдача MTProto-секрета                          |
| `GET  /internal/sub/{token}`      | HMAC        | sub-Worker → backend (edge subscription)        |
| `GET  /v1/webapp/bootstrap`       | initData    | Mini-App bootstrap (TODO)                       |
| `GET  /v1/subscription`           | initData    | Mini-App: моя подписка (TODO)                   |

## Миграции

```bash
alembic revision -m "init" --autogenerate
alembic upgrade head
```

## Security

- Internal endpoints требуют HMAC-SHA256 подписи (header `x-vlessich-sig`),
  clock skew ≤60s. Ключ `API_INTERNAL_SECRET` общий с ботом и sub-Worker.
- Xray UUID хранятся зашифрованными (libsodium secretbox, `API_SECRETBOX_KEY`).
- PII не логируется.
