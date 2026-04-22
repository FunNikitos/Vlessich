# Stage 10 — Auto-rebroadcast Deeplinks + Cron MTProto Rotation

Status: in_progress (branched off Stage 9 HEAD `19f759c`).

## Goal

Закрыть «забыл ротировать» риск и автоматически довести обновлённый
deeplink до затронутых юзеров без ручного админ-action'а:

1. **Cron rotation worker** — раз в N (default 1h) проверяет возраст
   ACTIVE shared MTProto секрета. Если старше `MTG_SHARED_ROTATION_DAYS`
   (default 30) — выполняет ту же логику, что `POST /admin/mtproto/rotate`
   с `actor_type='system'`.
2. **Broadcast worker** — слушает Redis stream `mtproto:rotated` (push
   из API после любой rotation), для каждого затронутого `tg_id` POST'ит
   на bot endpoint `/internal/notify/mtproto_rotated` с HMAC. Bot DM'ит
   юзеру обновлённый deeplink. RL 30/s global + 1/s per chat,
   idempotency 24h, cooldown 1h.

## Locked decisions (user, начало сессии Stage 10)

- **Cron policy**: shared-only by age (per-user — только ручная ротация
  через admin endpoint).
- **Transport**: API → Bot HTTP `/internal/notify/mtproto_rotated`,
  HMAC `x-vlessich-sig` (тот же secret/format, что Bot↔API).
- **Timing**: immediate per-event (не batch с админ-confirmation).
- **Branch base**: `feat/stage-9-mtproto-per-user` HEAD `19f759c`.

## Architecture

```
                  ┌──────────────── API ────────────────┐
cron tick (1h) ──▶│ mtproto_rotator worker              │
                  │  - SELECT ACTIVE shared secret      │
                  │  - if age > MTG_SHARED_ROTATION_DAYS│
                  │      → run rotate-shared (system)   │
                  │      → emit_rotation_event(...)     │
                  └─────────────┬───────────────────────┘
                                │
admin POST /admin/mtproto/      │ (Stage 8 endpoint)
        rotate ─────────────────┤  → emit_rotation_event(scope='shared')
admin POST /admin/mtproto/      │
        users/{uid}/rotate ─────┤  → emit_rotation_event(scope='user', user_id=uid)
                                │
                                ▼
                  Redis stream `mtproto:rotated`
                  (XADD MAXLEN ~ 10000)
                                │
                                ▼
                  ┌──── mtproto_broadcaster worker ─────┐
                  │ XREADGROUP consumer 'broadcast'     │
                  │  - resolve affected user_ids:       │
                  │      shared → all tg_ids в users    │
                  │              with ACTIVE Subscript. │
                  │      user   → just user_id          │
                  │  - per chat:                        │
                  │      - check Redis cooldown SET     │
                  │      - check idempotency SET (TTL)  │
                  │      - acquire RL token bucket      │
                  │      - POST bot /internal/notify/   │
                  │             mtproto_rotated         │
                  │      - on 2xx: SET cooldown 1h,     │
                  │                SET idempotency 24h, │
                  │                XACK                 │
                  │      - on 4xx: log + XACK (poison)  │
                  │      - on 5xx/network: NACK retry   │
                  └─────────────┬───────────────────────┘
                                │ HTTP HMAC POST
                                ▼
                  ┌──── Bot /internal/notify/... ───────┐
                  │  verify HMAC + ts skew              │
                  │  fetch fresh deeplink via api_client│
                  │  bot.send_message(tg_id, deeplink)  │
                  │  on TelegramAPIError: log + 200 OK  │
                  │    (broadcaster won't retry,        │
                  │     idempotency prevents duplicate) │
                  └─────────────────────────────────────┘
```

## Data flow (event payload)

Redis stream `mtproto:rotated` field map (XADD):
```
event_id   = uuid4 hex (stable, used for idempotency)
scope      = "shared" | "user"
secret_id  = uuid (new ACTIVE secret)
user_id    = "" (shared) | str(int) (user)
emitted_at = ISO-8601 UTC
```

Broadcaster builds per-chat idempotency key:
```
idem:mtproto_broadcast:{event_id}:{tg_id}   TTL 86400
cooldown:mtproto_broadcast:{tg_id}          TTL 3600
rl:mtproto_broadcast:global                 token bucket 30/s
rl:mtproto_broadcast:chat:{tg_id}           token bucket 1/s
```

Bot endpoint payload (POST `/internal/notify/mtproto_rotated`):
```json
{
  "event_id": "abc...",
  "scope": "shared",
  "tg_id": 12345,
  "emitted_at": "2026-..."
}
```
Bot НЕ принимает deeplink в payload — fetch'ит через api_client (single
source-of-truth, защита от утечки secret material через лог
broadcaster'а).

## Affected-user resolution

- **shared scope**: SELECT users.tg_id JOIN subscriptions
  WHERE subscriptions.status IN ('ACTIVE','TRIAL'). Это не идеально
  (юзер может не пользоваться MTProto), но в текущей модели нет
  таблицы «issued shared deeplinks» — derive из активных подписок.
  Альтернатива (deferred): отдельная таблица `mtproto_issue_log`
  (subscription_id, tg_id, scope, issued_at) — не делаем в Stage 10,
  чтобы не плодить миграции; AuditLog `mtproto_issued` уже есть, но
  query по `payload->>'tg_id'` дорогой и без индекса.
- **user scope**: ровно один `tg_id` (известен из event payload).

## Locked settings (env `API_*`)

| Env | Default | Назначение |
|---|---|---|
| `API_MTG_AUTO_ROTATION_ENABLED` | `false` | Master flag для rotator worker'а |
| `API_MTG_SHARED_ROTATION_DAYS` | `30` | Возраст ACTIVE shared, после которого rotator ротирует |
| `API_MTG_ROTATOR_INTERVAL_SEC` | `3600` | Период tick'ов rotator'а (1h) |
| `API_MTG_BROADCAST_ENABLED` | `false` | Master flag для emit + broadcaster |
| `API_MTG_BROADCAST_COOLDOWN_SEC` | `3600` | Минимум секунд между двумя DM одному tg_id |
| `API_MTG_BROADCAST_IDEMPOTENCY_TTL_SEC` | `86400` | TTL idempotency-ключа (event_id, tg_id) |
| `API_MTG_BROADCAST_RL_GLOBAL_PER_SEC` | `30` | Telegram global limit (не >30) |
| `API_MTG_BROADCAST_RL_PER_CHAT_SEC` | `1` | Telegram per-chat limit (не <1) |
| `API_MTG_BROADCAST_STREAM_MAXLEN` | `10000` | XADD MAXLEN ~ для truncate |

Bot side (env `BOT_*`):

| Env | Default | Назначение |
|---|---|---|
| `BOT_INTERNAL_NOTIFY_ENABLED` | `true` | Master flag для notify endpoint |
| `BOT_INTERNAL_NOTIFY_HOST` | `0.0.0.0` | Listen host |
| `BOT_INTERNAL_NOTIFY_PORT` | `8081` | Listen port (отдельный от webhook 8080) |

## Audit & metrics

AuditLog actions (новые):
- `mtproto_auto_rotated` — actor_type='system', payload `{cloak_domain, revoked_secret_id, age_days}`.
- `mtproto_broadcast_sent` — actor_type='system', target_id=event_id, payload `{tg_id, scope, status: 'ok'|'failed'|'cooldown'|'duplicate'}`.

Prometheus (новые в `app.metrics`):
- `mtproto_broadcast_sent_total{status}` Counter — ok|failed|cooldown|duplicate.
- `mtproto_auto_rotation_total{result}` Counter — rotated|skipped|error.
- `mtproto_shared_secret_age_seconds` Gauge — текущий возраст ACTIVE shared.

Alert rules (`infra/prometheus/rules/vlessich.yml`):
- `MtprotoSharedSecretStale` — `mtproto_shared_secret_age_seconds > MTG_SHARED_ROTATION_DAYS * 86400 * 1.2 for 1h` (warning, означает rotator выключен или сломан).
- `MtprotoBroadcastFailures` — `rate(mtproto_broadcast_sent_total{status="failed"}[15m]) > 0.1` (warning).

## Error codes (новые в `ApiCode`)

- `BROADCAST_FAILED` = `"broadcast_failed"` — для bot endpoint upstream errors.
- `NOTIFICATION_DISABLED` = `"notification_disabled"` — bot endpoint когда master flag off.

## Rollout / rollback

**Rollout**:
1. Deploy с `API_MTG_AUTO_ROTATION_ENABLED=false`, `API_MTG_BROADCAST_ENABLED=false`.
2. Поднять `mtproto_rotator` + `mtproto_broadcaster` workers (idle).
3. Поднять bot с `/internal/notify/mtproto_rotated` endpoint.
4. Smoke-test в staging: ручной rotate с включённым broadcast → проверить DM.
5. Включить `API_MTG_BROADCAST_ENABLED=true`.
6. Через 24h без incidents — включить `API_MTG_AUTO_ROTATION_ENABLED=true`.

**Rollback**: вернуть оба flags в `false`. Workers продолжат работать
вхолостую (rotator skip-loop, broadcaster idle на пустом stream).

## Commits T1..T10

- **T1** (this) — `docs/plan-stage-10.md`.
- **T2** — settings + ApiCode (`MTG_AUTO_ROTATION_*`, `MTG_BROADCAST_*`, `BROADCAST_FAILED`, `NOTIFICATION_DISABLED`).
- **T3** — `api/app/services/mtproto_broadcast.py` (Redis RL/cooldown/idempotency + XADD).
- **T4** — `api/app/workers/mtproto_rotator.py` + helper `_rotate_shared_in_tx` extracted from admin router.
- **T5** — wiring `emit_rotation_event(...)` в admin rotate-shared / per-user rotate routes; metrics gauge update в rotator.
- **T6** — `api/app/workers/mtproto_broadcaster.py` (XREADGROUP loop + HMAC POST + retry).
- **T7** — bot side: `bot/app/notify_server.py` aiohttp app + HMAC verify + DM logic; wire-up в `bot/app/main.py` параллельно с polling/webhook.
- **T8** — `docker-compose.dev.yml` сервисы `mtproto_rotator`, `mtproto_broadcaster`; `.env.example` обновления.
- **T9** — tests: rotator (age-detection, disable-flag), broadcast service (RL, cooldown, idempotency), broadcaster HTTP path, bot notify endpoint HMAC.
- **T10** — docs: CHANGELOG `[0.10.0]`, `docs/ARCHITECTURE.md` §22, README, alerts/dashboard updates.

## Verification per commit

```powershell
python -c "import ast,glob; [ast.parse(open(f,encoding='utf-8').read(),f) for f in glob.glob('api/**/*.py', recursive=True)]; print('OK')"
python -c "import ast,glob; [ast.parse(open(f,encoding='utf-8').read(),f) for f in glob.glob('bot/**/*.py', recursive=True)]; print('OK')"
python -c "import yaml,json; yaml.safe_load(open('infra/prometheus/rules/vlessich.yml',encoding='utf-8')); yaml.safe_load(open('docker-compose.dev.yml',encoding='utf-8')); json.load(open('infra/grafana/dashboards/vlessich.json',encoding='utf-8')); print('OK')"
Get-ChildItem api\app,api\tests,bot\app -Recurse -Include *.py | Select-String -Pattern '# type: ignore'
```

## Out-of-scope (deferred)

- `mtproto_issue_log` отдельной таблицей — пока derive из subscriptions.
- Per-user cron auto-rotation — только ручная (locked decision).
- Mini-App «MTProto rotated» banner — broadcast делается в Telegram DM.
- Retry-after-X queue для bounced DM — broadcaster XACK'ает и
  полагается на следующее rotation event (cooldown TTL спадёт).
