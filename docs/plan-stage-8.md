# Stage 8 — MTProto (mtg) Container Wiring + Admin Rotation

**Версия:** 1.0
**Дата:** 22.04.2026
**Статус:** ⏳ in progress
**Предпосылка:** Stage 7 закрыт (ветка `feat/stage-7-logs-alerts-ru-probing`,
HEAD `5f691e9`). API + prober + Loki/alerts готовы.
**Ветка:** `feat/stage-8-mtg-integration` (от stage-7).
**TZ refs:** §9A (MTProto), §10.2 (mtg metrics), §11A.4 (admin
rotate).

## Утверждённые решения (locked)

### Scope (в этом этапе)

1. **mtg в `docker-compose.dev.yml`**: сервис `mtg` (image
   `nineseconds/mtg:2`), монтирует `mtg/config.toml`,
   exposes `:8443` (Fake-TLS) и `127.0.0.1:9410` (`/metrics`).
   Healthcheck по `/metrics`.
2. **API startup seed**: при `lifespan startup` API проверяет наличие
   хотя бы одного `MtprotoSecret(scope='shared', status='ACTIVE')`.
   Если пусто **и** `MTG_SHARED_SECRET_HEX` задан в env — вставляет
   row (`secret_hex` = env value, `cloak_domain` = `MTG_SHARED_CLOAK`,
   default `www.microsoft.com`). Idempotent: повторный startup ничего
   не меняет.
3. **`POST /internal/mtproto/issue` scope='user' → 501**: `ApiCode.NOT_IMPLEMENTED`,
   message «Per-user MTProto будет в Stage 9». shared scope работает
   как раньше (берёт row из пула).
4. **`POST /admin/mtproto/rotate`** (superadmin): генерирует новый
   `secret_hex` (`secrets.token_hex(16)`), REVOKE текущий ACTIVE
   shared, INSERT новый ACTIVE с тем же / новым cloak (тело запроса).
   Возвращает `{secret_hex, cloak_domain, full_secret, mtg_config_line}`
   для копипаста в `mtg/config.toml`. AuditLog
   `mtproto_rotated`. Реальный restart mtg — ручной (out of scope).
5. **Prometheus scrape mtg**: добавить job `vlessich-mtg` в
   `infra/grafana/README.md`. Alert `MtgDown` в
   `infra/prometheus/rules/vlessich.yml`. Dashboard: новая панель
   «MTG connections» (best-effort — depends on real mtg metrics).

### НЕ в этом этапе

- Per-user MTProto secrets (нужен mtg [replicas] orchestration или N
  containers — Stage 9).
- Auto-rotation (cron / schedule) — Stage 9.
- Auto-rebroadcast deeplinks всем юзерам после rotate — Stage 9.
- Admin UI page для mtg — Stage 9 (endpoint есть, фронт TODO).

### Data model

Без изменений в этом этапе. `mtproto_secrets.scope='user'` колонки
остаются (используются только в Stage 9).

### Settings (новые)

| Env | Default | Назначение |
|---|---|---|
| `API_MTG_SHARED_SECRET_HEX` | unset | 32-hex random секрет для seed shared pool. Unset → seed skipped (dev). |
| `API_MTG_SHARED_CLOAK` | `www.microsoft.com` | Cloak domain для seeded shared secret. |

(Existing `API_MTG_HOST`, `API_MTG_PORT`, `API_MTG_CLOAK_DOMAINS` не
меняются.)

### Errors

`ApiCode.NOT_IMPLEMENTED = "not_implemented"` — новый код для
scope='user' issue.

---

## T-list

- **T1** — План (этот файл).
- **T2** — `app/config.py`: `mtg_shared_secret_hex: SecretStr | None`
  + `mtg_shared_cloak: str`. `app/errors.py`:
  `ApiCode.NOT_IMPLEMENTED`. `api/.env.example`: примеры env.
- **T3** — API startup hook (`app/main.py` lifespan): seed shared
  MtprotoSecret idempotent. `app/routers/mtproto.py` scope='user'
  возвращает 501 `not_implemented`.
- **T4** — `app/routers/admin/mtproto.py` (новый): `POST
  /admin/mtproto/rotate` superadmin-only. Body: `{cloak_domain?:
  str}`. Response: `{full_secret, secret_hex, cloak_domain,
  config_line, port, host}`. AuditLog `mtproto_rotated`. Регистрация
  в `main.py`.
- **T5** — `docker-compose.dev.yml`: сервис `mtg` (image
  `nineseconds/mtg:2`, mount `./mtg/config.toml`, port `8443`,
  expose `127.0.0.1:9410`, healthcheck). `infra/grafana/README.md`:
  job `vlessich-mtg`. `infra/prometheus/rules/vlessich.yml`: alert
  `MtgDown`. `infra/grafana/dashboards/vlessich.json`: best-effort
  panel «MTG up».
- **T6** — Tests:
  - `api/tests/test_mtproto_issue.py` — расширить: scope='user' →
    501 `not_implemented`.
  - `api/tests/test_admin_mtproto.py` — happy-path rotate (superadmin,
    REVOKE old, INSERT new, AuditLog written) + 403 для support.
- **T7** — Docs: CHANGELOG `[0.8.0]`, ARCHITECTURE §19, root README,
  api/README, mtg/README.md уточнить env-link.

---

## Acceptance criteria

- [ ] API startup без `MTG_SHARED_SECRET_HEX` не падает (no-op seed).
- [ ] С env set + пустой таблицей → 1 shared row. Re-start не дублирует.
- [ ] `POST /internal/mtproto/issue {scope:'user'}` → 501
      `not_implemented`.
- [ ] `POST /admin/mtproto/rotate` superadmin → REVOKE old, INSERT new,
      audit row.
- [ ] `POST /admin/mtproto/rotate` support → 403.
- [ ] `docker compose up mtg` поднимает контейнер healthy (manual; в
      CI mtg не запускаем).
- [ ] `infra/prometheus/rules/vlessich.yml` валиден (yaml + schema
      test).
- [ ] AST parse api/**/*.py чист.
- [ ] CHANGELOG `[0.8.0]` + ARCHITECTURE §19 написаны.
