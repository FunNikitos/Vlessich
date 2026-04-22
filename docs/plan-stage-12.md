# Stage 12 — Smart-routing + RU-lists + AdBlock

Status: in_progress (branched off Stage 11 HEAD `6b2d7d3`).

## Goal

Закрыть DoD-пункт из TZ §16 «Smart-режим: `sber.ru` идёт direct,
`youtube.com` через FI». Построить routing-rule generator, который
бот/Mini-App отдают клиенту (singbox JSON primary, clash YAML fallback),
и агрегатор RU-geosite/ads источников с auto-pull каждые 6h.

Стоит отдельно от Stage 11: никакого пересечения с billing-flow, кроме
использования общей `Subscription.adblock` / `Subscription.smart_routing`
boolean'ов (уже существуют в модели).

## Routing profiles (user)

Бот предлагает **выбор профиля** при получении конфига. Внутренне
это комбинация уже существующих `Subscription.smart_routing` и
`Subscription.adblock` bool'ов + новый `Subscription.routing_profile`
enum (`full` / `smart` / `adblock` / `plain`).

| Профиль    | smart_routing | adblock | Что делает                                                  |
|------------|---------------|---------|-------------------------------------------------------------|
| `full`     | on            | on      | RU-домены direct, остальное proxy, реклама block            |
| `smart`    | on            | off     | RU direct, остальное proxy, реклама проходит                |
| `adblock`  | off           | on      | Всё direct (VPN off-like), только реклама block             |
| `plain`    | off           | off     | Всё через VPN, без умной маршрутизации (как до Stage 12)    |

`plain` = исторический режим (Stage 2 sub_payload). `full` = DoD TZ §16.
`adblock` = TZ §18.6 «DNS-only тариф» — только блокировка рекламы без
реального прокси (юзер маршрутизирует всё direct, получая только
AGH+routing adblock).

Бот (`/config` или кнопка «📥 Получить конфиг»):
1. Показывает inline-меню с 4 профилями + кратким описанием.
2. На клик: `POST /internal/subscriptions/{id}/profile` (HMAC) →
   апдейт `routing_profile` + boolean'ов.
3. Выдаёт deep-link `https://sub.<brand>/<sub_url_token>?fmt=singbox|clash`
   (фактические bool'ы читаются из Subscription при отдаче payload'а).

## Locked decisions (user, начало Stage 12)

- **Ruleset output formats**: `singbox` JSON (primary — Hiddify /
  v2rayTun / Karing / NekoBox) + `clash` YAML (fallback — Clash Verge /
  Happ / mihomo).
- **RU-lists sources**:
  - `https://github.com/runetfreedom/russia-blocked-geoip` (ASN / IP
    CIDR для reverse-direct лишних РФ-маршрутов) — **отложено**, не
    в MVP (требует geoip merge).
  - `https://community.antifilter.network/` — фактический антифильтр
    РКН реестр (reverse: всё что заблокировано → proxy). Этот source
    canonical для «обходим блоки».
  - `https://github.com/v2fly/domain-list-community` — geosite
    `category-ru` (direct) + `category-ads-all` (block). Только
    human-readable `data/*` файлы, без бинарного geosite.dat.
  - Кастомный YAML в репо `infra/smart-routing/custom-ru.yml` с
    категориями TZ §8.3 (банки / госуслуги / Yandex / VK group /
    маркетплейсы / стриминг / доставка / связь / СБП / прочее).
- **Pull interval**: 6h (`API_RULESET_PULL_INTERVAL_SEC=21600`).
- **AdBlock scope**: только routing-level (`geosite:category-ads-all
  → block` + custom ads-домены). AGH DNS-level списки управляются
  Ansible (Stage 1 node-provisioning), **не** админкой.
- **Ruleset storage**: Postgres.
  - `ruleset_sources` — запись на источник (url / kind / enabled).
  - `ruleset_snapshots` — snapshot с `payload JSONB` (canonical
    internal form), `pulled_at`, `sha256`, `source_id`, versioning.
  - `active_snapshot_id` на `ruleset_sources` для rollback.

## Architecture

```
           ┌─────── ruleset_puller (worker, api-image) ───────┐
 every 6h  │   for each ruleset_sources.enabled:              │
           │     HTTP GET url (timeout 30s, retries 3)        │
           │     parse → canonical domains[] + cidrs[]        │
           │     sha256 → dedup                               │
           │     INSERT ruleset_snapshots if new sha          │
           │     UPDATE source.active_snapshot_id = new       │
           └──────────────────────┬───────────────────────────┘
                                  │
                                  ▼
                    ┌─── RoutingBuilder (pure) ───┐
                    │ compose canonical:          │
                    │   direct = v2fly:ru ∪ custom:ru ∪ custom:banks…
                    │   block  = v2fly:ads ∪ custom:ads
                    │   proxy  = default (tail)
                    │ emit per-format:            │
                    │   singbox JSON (route.rules)│
                    │   clash YAML (rules:)        │
                    └─────────────┬───────────────┘
                                  │
                                  ▼
           ┌─── /internal/smart_routing/config (HMAC) ───┐
           │   GET ?sub_token=…&fmt=singbox|clash        │
           │   → fetch Subscription → merge inbounds[]   │
           │     (from Stage 2 sub_payload)              │
           │     + routing block (smart_routing on?)     │
           │     + rule-sets (adblock on?)               │
           └─────────────────────────────────────────────┘
                                  │
                                  ▼
               sub-Worker ←─── edge subscription URL
               (already exists from Stage 2;
                we extend payload, не меняем Worker API)
```

## Tasks (atomic commits)

### T1 — docs: plan
- `docs/plan-stage-12.md` (this file).

### T2 — config + ApiCode
- `api/app/config.py`: `ruleset_pull_interval_sec=21600`,
  `ruleset_puller_enabled=false` (master flag, off by default).
- `api/app/errors.py`: `RULESET_NOT_FOUND`, `RULESET_SOURCE_DISABLED`,
  `RULESET_PULL_FAILED`, `RULESET_FORMAT_UNKNOWN`.
- `api/.env.example`: `API_RULESET_*`.

### T3 — migration 0007
- `ruleset_sources(id uuid pk, kind text check, name text uniq,
  url text, enabled bool, active_snapshot_id uuid fk, created_at)`.
- `ruleset_snapshots(id uuid pk, source_id fk, sha256 char(64) uniq
  on (source_id, sha256), payload jsonb not null, pulled_at,
  meta jsonb)`.
- index `ix_ruleset_snapshots_source_pulled_at`.
- `subscriptions.routing_profile text NOT NULL DEFAULT 'plain'
  CHECK (routing_profile IN ('full','smart','adblock','plain'))`.
- backfill: existing rows → `'plain'` (no behaviour change).

### T4 — models
- `api/app/models.py`: `RulesetSource` + `RulesetSnapshot`.
- `Subscription.routing_profile: Mapped[str]`.

### T5 — service: canonical parsers
- `api/app/services/ruleset/parsers.py`:
  - `parse_antifilter(text) -> list[str]` (domains + CIDRs).
  - `parse_v2fly_geosite(text, category) -> list[str]`.
  - `parse_custom_yaml(raw: bytes) -> list[Rule]`.
- tests: fixtures для каждого parser.

### T6 — service: puller
- `api/app/services/ruleset/puller.py`:
  - `async def pull_source(session, src, http)` → вставка snapshot
    idempotent по sha256.
  - `async def pull_all_enabled(session, http)`.

### T7 — worker: ruleset_puller
- `api/app/workers/ruleset_puller.py` — тикер раз в
  `settings.ruleset_pull_interval_sec`, Prometheus exporter
  (`vlessich_ruleset_pull_total{source,status}`,
  `vlessich_ruleset_last_pulled_seconds{source}`).
- `docker-compose.dev.yml`: новый service `ruleset_puller`.

### T8 — service: routing builder
- `api/app/services/ruleset/builder.py`:
  - `build_singbox(sub, smart_on, adblock_on, sources) -> dict`.
  - `build_clash(sub, smart_on, adblock_on, sources) -> str` (YAML).
- tests: snapshot-тесты на обе формы.

### T9 — internal routing endpoint
- `api/app/routers/smart_routing.py`:
  - `GET /internal/smart_routing/config?sub_token=…&fmt=singbox|clash`
    (HMAC) → JSON/YAML.
  - `POST /internal/subscriptions/{tg_id}/profile` (HMAC) →
    смена `routing_profile` + sync `smart_routing` / `adblock` bool'ов.
- wire в `app.main`.

### T10 — admin endpoints
- `GET  /admin/ruleset/sources` (readonly+).
- `POST /admin/ruleset/sources` (superadmin) — add URL.
- `PATCH /admin/ruleset/sources/{id}` (superadmin) — enable/disable.
- `POST /admin/ruleset/sources/{id}/pull` (superadmin) — force pull.
- `GET  /admin/ruleset/snapshots?source_id=…` (readonly+).

### T11 — admin UI (React)
- Page «Routing» → таблица sources, toggle enabled, force-pull button,
  snapshot history modal.

### T12 — Mini-App integration
- Toggle «Умный режим» и «AdBlock» в Mini-App Settings —
  уже есть из Stage 3. Добавить preview текущих rules (domain count).

### T12B — Bot config flow (NEW)
- `bot/app/handlers/config.py`:
  - `/config` command + callback `cfg:start` (button «📥 Получить конфиг»
    в main menu).
  - Inline-меню 4 профилей: `full` / `smart` / `adblock` / `plain`
    с подписью «Что это даёт».
  - На клик — `api_client.set_routing_profile(tg_id, profile)` →
    DM с deep-link'ом `https://sub.<brand>/<token>?fmt=singbox` и
    альтернативой `?fmt=clash`.
- `bot/app/services/api_client.py`:
  `set_routing_profile(tg_id, profile) -> SubscriptionOut`.
- `bot/app/texts.py`: `CONFIG_PROMPT`, `CONFIG_PROFILE_*`,
  `CONFIG_DELIVERED`.

### T13 — seed defaults
- `app.main.lifespan`: seed default sources (antifilter, v2fly-ru,
  v2fly-ads, custom-ru из repo) если пусто. Idempotent.

### T14 — metrics + alerts
- Counters: `ruleset_pull_total{source,status}`,
  `ruleset_snapshot_bytes{source}` histogram.
- Alerts: `RulesetPullFailures` (>3 fails/6h per source),
  `RulesetStale` (source without successful pull >24h).

### T15 — tests
- Parser tests (фикстуры).
- Puller integration (real HTTP mocked via aioresponses).
- Builder snapshot tests (singbox + clash).
- Smart_routing endpoint test (HMAC).
- Admin endpoints RBAC.

### T16 — docs
- `CHANGELOG.md` [0.12.0].
- `ARCHITECTURE.md §24`.
- `api/README.md`, root `README.md` — endpoints + env.

## Non-goals (defer)

- geoip binary merges (Loyalsoldier geoip.dat / geosite.dat) — parser
  сложный, reverse-geoip уже отдаётся Xray'ем на ноде через встроенные
  `geosite.dat`.
- AGH list sync / admin push (управляем Ansible-ом).
- Auto-apply новых rules без re-subscribe — клиенты сами перечитывают
  sub URL; push-уведомление об обновлении — отдельный Stage.
- Per-user custom rules (advanced) — MVP раздаёт один общий ruleset
  всем юзерам, тумблерится только `smart_routing` / `adblock` bool.

## Feature flags

- `API_RULESET_PULLER_ENABLED` (default `false`) — master flag.
  Off → worker idle (только expose metrics). On → активно pull'ит.
- `API_RULESET_PULL_INTERVAL_SEC` (default `21600`, 6h).
- `API_SMART_ROUTING_ENABLED` (default `false`) — off →
  `/internal/smart_routing/config` → 503 `ruleset_not_found`, и
  Mini-App toggle скрыт.

## DoD (acceptance)

- [ ] Смарт-режим: clash/singbox YAML/JSON возвращается на `GET
      /internal/smart_routing/config` для ACTIVE sub.
- [ ] Пулл каждые 6h; source failure логируется + алерт через 3 fails.
- [ ] Админка: CRUD sources + force-pull + history.
- [ ] Smoke: `sber.ru` → direct; `youtube.com` → proxy;
      `*.doubleclick.net` → block.
- [ ] Tests coverage ≥80% для затронутых модулей.
- [ ] CHANGELOG + ARCHITECTURE §24.

## Risks

- **License antifilter**: public community list, но reuse требует
  attribution — указать в RUNBOOK.
- **Size blowup**: full антифильтр ~200k domains. Рендер в singbox
  → JSON ~5MB. Edge-Worker лимит — 10MB response; наблюдаем.
  Если упрёмся — перейдём на **rule-set remote URL** (singbox
  `rule_set` тип `remote`), а не inline.
- **v2fly rate-limit**: GitHub raw limits — кэшируем в Postgres,
  обращаемся раз в 6h.
- **Client compat**: `clash` YAML — разные диалекты
  (premium vs core vs mihomo). Сначала mihomo (самый строгий), потом
  расширяем.
