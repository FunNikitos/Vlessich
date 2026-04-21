# Stage 7 — Log Aggregation + Prometheus Alerts + Residential RU Probing

**Версия:** 1.0
**Дата:** 21.04.2026
**Статус:** ⏳ in progress
**Предпосылка:** Stage 6 завершён (ветка `feat/stage-6-observability`,
HEAD `aa252d3`). API + prober экспонируют Prometheus metrics, captcha
включена.
**Ветка:** `feat/stage-7-logs-alerts-ru-probing` (от stage-6).
**TZ refs:** §11.4 (residential RU-прокси для probing), §15 (Loki +
Prometheus), §13 (SLO/alerting).

## Утверждённые решения (locked)

### Scope

- **В этом этапе:**
  1. **Loki + promtail**: scrape JSON-логов structlog из compose-services
     в Loki. LogQL запросы в Grafana.
  2. **Prometheus alert rules**: фиксированный yaml с правилами
     (no alertmanager wiring — это deploy-time, не code).
  3. **Residential RU probe backend**: вторая реализация
     `ProbeBackend` Protocol — HTTP CONNECT через residential SOCKS/HTTP
     прокси + DNS resolve. Конфигурируется через `API_RU_PROXY_URL`.
     Если unset — отключено (dev).
  4. **Dual-probe mode**: prober поддерживает **список** бэкендов, для
     каждой ноды пробит все; запись `NodeHealthProbe.probe_source`
     (`edge` / `ru`). State machine учитывает **`edge` only** —
     RU-probe для телеметрии (дашборд), не для BURN.
- **НЕ в этом этапе:** alertmanager deploy, PagerDuty/Slack
  integration, реальные контракты с резидент-прокси, RU-probe как
  blocker для BURN (requires more thought re: false positives).

### Data model change

Добавляем колонку `NodeHealthProbe.probe_source` (varchar(16),
`NOT NULL DEFAULT 'edge'`) + Alembic migration. Existing rows = 'edge'.

Index `(node_id, probed_at DESC, probe_source)` — для
дашборда-по-источнику.

### RU ProbeBackend (MVP)

- Env: `API_RU_PROXY_URL` — формат `socks5://user:pass@host:port` или
  `http://user:pass@host:port`. Unset → backend не создаётся.
- Реализация: `httpx.AsyncClient(proxies=...)` делает `GET http://hostname/`
  на порт probe_port с таймаутом. Any 2xx/3xx/4xx/5xx = `ok=True`
  (нода отвечает, хотя бы TCP live). `ConnectError`/`TimeoutError` =
  `ok=False`.
- **Rationale**: в РФ блокировка часто на уровне TCP RST / DNS — если
  из РФ видно что порт слушает, нам важно только reachability. HTTPS/TLS
  handshake парсинг — отдельная работа (не MVP).

### Prober wiring

```python
backends: list[tuple[str, ProbeBackend]] = []
backends.append(("edge", TcpProbeBackend(...)))
if settings.ru_proxy_url:
    backends.append(("ru", HttpProxyProbeBackend(...)))
```

- `run_once`: per-node × per-backend = N×M probes, all in
  `asyncio.gather`. Запись всех в БД одной транзакцией.
- **State machine** смотрит только `edge` results (как раньше), чтобы
  RU-прокси downtime не зажигал false BURN.

### Metrics additions

- `vlessich_probe_duration_seconds{ok, source}` — добавить label
  `source`.
- `vlessich_probe_total{ok, source}` — same.
- Existing queries в дашборде filter by `source="edge"` для
  совместимости; new panel: «RU vs Edge success ratio».

### Loki + promtail

- `infra/loki/` — промтейл config + loki config для самостоятельного
  запуска (не в dev compose).
- Structlog → JSON — уже включено в api/worker. Promtail парсит
  `{"level","msg",...}` и label'ит по service name.
- Labels: `service` (api|reminders|prober|bot), `level`, `env`.

### Alert rules

`infra/prometheus/rules/vlessich.yml`:

1. **NodeBurnSpike**: `increase(vlessich_node_burned_total[15m]) > 2`
   → warning.
2. **ProbeSuccessLow**: edge success ratio < 0.8 for 10m → warning.
3. **AdminCaptchaFailSpike**: `rate(vlessich_admin_login_total{result=
   "captcha_fail"}[5m]) > 0.2` → info.
4. **ApiP95Latency**: p95 http_request_duration > 1s for 5m → warning.
5. **ProberDown**: `up{job="vlessich-prober"} == 0` for 5m → critical.

---

## T-list

- **T1** — Plan (этот файл).
- **T2** — `NodeHealthProbe.probe_source` column + Alembic migration;
  model update; ensure `GET /admin/nodes/{id}/health` queries with
  `probe_source='edge'` filter (keeps current percentile semantics).
- **T3** — Residential RU `ProbeBackend`: `HttpProxyProbeBackend` в
  `app/workers/probe_backends.py` (новый модуль + перенос
  `TcpProbeBackend`). Integration в `prober.main`: list of backends.
- **T4** — Multi-backend `run_once` + state machine сохраняет только
  `edge` transitions. Metrics label `source` added to `PROBE_*`.
  Config: `ru_proxy_url`, `ru_probe_timeout_sec`.
- **T5** — `infra/prometheus/rules/vlessich.yml` + `infra/loki/`
  configs + `infra/loki/README.md`.
- **T6** — Tests:
  - `test_probe_backends.py` — `TcpProbeBackend` (asyncio stub +
    timeout), `HttpProxyProbeBackend` (httpx MockTransport).
  - `test_prober_multi_backend.py` — scripted fake backends for edge+ru,
    state machine only reacts to edge, rows written with probe_source.
  - `test_alert_rules.py` — parse yaml (schema valid).
- **T7** — Docs: CHANGELOG `[0.7.0]`, ARCHITECTURE §18, READMEs.

---

## Acceptance criteria

- [ ] Alembic migration adds `probe_source` column + backfill 'edge'.
- [ ] Prober поднимается с только edge backend (RU_PROXY_URL пустой) —
      без ошибок.
- [ ] Если `API_RU_PROXY_URL` set — `run_once` делает per-node 2 probes,
      обе записаны с разным `probe_source`.
- [ ] BURN transition **не** срабатывает от RU fails — только от edge.
- [ ] `vlessich_probe_total{source="ru"}` виден после tick с
      ru-бэкендом.
- [ ] `infra/prometheus/rules/vlessich.yml` валиден (yaml + promtool
      schema-level).
- [ ] Все новые `.py` парсятся AST.
- [ ] CHANGELOG, ARCHITECTURE §18 актуализированы.
