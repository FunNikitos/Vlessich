# Stage 5 — Active Probing + IP Rotation

**Версия:** 1.0
**Дата:** 21.04.2026
**Статус:** ⏳ in progress
**Предпосылка:** Stage 4 завершён (ветка `feat/stage-4-admin-ui`, HEAD
`a92ce74`). Таблица `node_health_probes` и endpoint
`GET /admin/nodes/{id}/health` уже существуют.
**Ветка:** `feat/stage-5-probing` (создана от `feat/stage-4-admin-ui`).
**TZ refs:** §11.4 (авто-ротация IP), §16 Definition-of-Done (пункт про
блокировку FI-IP), §10 (health-check каждые 6ч — заменяем на конфиг).

## Утверждённые решения (locked)

- **Probe transport (MVP)** = **TCP-connect** из control-plane на
  `hostname:443` с timeout. Это проверяет, что нода онлайн и порт 443
  принимает соединение. Без TLS-handshake / xray-knife — пока не нужно,
  контракт минимальный, работает против Docker/VPS down-time.
- **Residential RU-proxies** (TZ §11.4) — **НЕ в этом этапе**. Причины:
  требует внешних контрактов, секретов, сетевой инфраструктуры, выходит
  за рамки чисто-кодового stage. Оставляем архитектурный hook — в
  `ProbeBackend` протоколе, чтобы Stage 6 подмешал RU-провайдер без
  переписывания.
- **Interval** = `PROBE_INTERVAL_SEC` (default **60s**). Значительно
  чаще чем в TZ (6h), т.к. в BURN-логике нужна быстрая реакция.
- **Timeout** = `PROBE_TIMEOUT_SEC` (default **5s**).
- **Concurrency** = asyncio `gather` со всеми нодами в одном tick;
  заблокированная нода не тормозит остальные.
- **Burn threshold** = **3 consecutive failures** → `status` переходит в
  `BURNED`, пишется `AuditLog(action="node_burned")`. Если нода уже
  `BURNED` — просто обновляем `last_probe_at`.
- **Recover threshold** = **5 consecutive successes** после BURNED →
  автовосстановление в `HEALTHY` + `AuditLog("node_recovered")`. Пять
  > burn threshold для hysteresis.
- **MAINTENANCE nodes** — **не проверяются** (админ сам управляет).
  Probes не пишутся. `last_probe_at` не обновляется.
- **Consecutive counter** — хранится in-memory в самом воркере (не в
  БД), рассчитывается по запросу из последних N `NodeHealthProbe`
  записей при старте воркера. Это упрощает транзакционность.
- **`last_probe_at`** обновляется в таблице `nodes` только при
  успешном записывании probe-строки. Timestamp — `func.now()` серверный.
- **Manual rotate endpoint** = `POST /admin/nodes/{id}/rotate`
  (superadmin). Семантика: админ подтверждает, что нода отротирована
  (физически, снаружи), backend сбрасывает состояние в `HEALTHY`,
  обнуляет `current_ip` (новый IP придёт с probe или патчится отдельным
  PATCH), audit `node_rotated`. Реальный hoster-API hook — **не** в этом
  этапе (требует Aeza/PQ auth, key-storage).
- **Deployment** = отдельный docker-compose service `prober` (образ api,
  CMD `python -m app.workers.prober`). Как `reminders`. Graceful
  shutdown: SIGTERM → доделать текущий tick → exit.
- **Observability** — structlog с `node_id`, `hostname`, `ok`,
  `latency_ms`, `consecutive_fails`. Prometheus metrics — **не в этом
  этапе** (Stage 6).

---

## 0. Контекст

Stage 4 дал UI и API `GET /admin/nodes/{id}/health`. Сейчас таблица
`node_health_probes` пуста в проде, потому что никто в неё не пишет.
Stage 5 закрывает эту дырку:

1. Фоновый воркер `prober` пишет probe-строки.
2. Логика burn/recover обновляет `nodes.status` автоматически.
3. Админ имеет кнопку «rotate» для подтверждения ручной ротации.

---

## T-list

- **T1** — План (этот файл).
- **T2** — Worker `app/workers/prober.py`:
  - `ProbeBackend` Protocol с методом `async probe(hostname, port) →
    ProbeResult`.
  - `TcpProbeBackend` — дефолтная реализация через `asyncio.open_connection`.
  - `run_once(session_maker, backend, thresholds)` — один tick: выбрать
    все `Node` с `status != 'MAINTENANCE'`, probe в parallel, записать
    `NodeHealthProbe` строки в одной транзакции; применить burn/recover.
  - `main()` — loop с `asyncio.sleep` + signal handler.
  - Config в `Settings`: `probe_interval_sec`, `probe_timeout_sec`,
    `probe_port`, `burn_threshold`, `recover_threshold`.
- **T3** — BURN/recover transitions, audit writes, test-seam-friendly.
- **T4** — `POST /admin/nodes/{id}/rotate` endpoint в `admin/nodes.py`.
- **T5** — `docker-compose.dev.yml` добавить `prober` service + api
  README обновить с env-vars.
- **T6** — Тесты:
  - `test_prober.py` — фейковый `ProbeBackend`, проверка: 3 fails →
    BURNED, 5 ok после BURNED → HEALTHY, MAINTENANCE не пробится,
    NodeHealthProbe рядом.
  - `test_admin_nodes_rotate.py` — rotate endpoint: RBAC, audit, clear
    current_ip, status→HEALTHY.
- **T7** — Docs: CHANGELOG `[0.5.0]`, ARCHITECTURE §16 «Active probing»,
  root README добавить prober row.

---

## Acceptance criteria

- [ ] `prober` service стартует в compose без падений при пустой БД.
- [ ] Для ноды где `hostname` недоступен — пишутся `ok=false` строки.
- [ ] После 3 подряд фейлов — `nodes.status='BURNED'` + `AuditLog`.
- [ ] После 5 подряд OK — `nodes.status='HEALTHY'` + `AuditLog`.
- [ ] `MAINTENANCE` ноды пропускаются.
- [ ] `POST /admin/nodes/{id}/rotate` (superadmin) = 200,
  `status='HEALTHY'`, `current_ip=null`, audit запись.
- [ ] Все новые файлы парсятся AST.
- [ ] Нет `# type: ignore`, `as any`, пустых except.
