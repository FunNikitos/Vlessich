# Stage 3 — Mini-App визуал (Spotify-dark) + backend webapp-endpoints

**Версия:** 1.0
**Дата:** 21.04.2026
**Статус:** ⏳ pending approval
**Предпосылка:** Stage 2 завершён (ветка `feat/stage-2-edge`, HEAD `3def1e1`).
**Ветка:** `feat/stage-3-miniapp` (создана от `feat/stage-2-edge`).
**Срок:** ~14–18 часов работы.

## Утверждённые решения (locked)

- **Authn webapp → backend** = **Telegram `initData` HMAC-SHA256**
  (TZ §11B). Backend verify через `bot_token` (secret_key =
  `hmac_sha256(b"WebAppData", bot_token)`, затем
  `hmac_sha256(secret_key, data_check_string).hex()` сравнивается
  constant-time). Заголовок — `x-telegram-initdata: <raw query string>`.
  Clock skew `auth_date` ≤ 24h. Alternative (собственный session-cookie
  с login-flow) отвергнут: избыточно, нарушает Mini-App UX.
- **Sub-URL для VPN-клиентов** = публичный
  `https://sub.<domain>/<sub_token>?client=<v2ray|clash|singbox|surge|raw>`
  (sub-Worker из Stage 2). Mini-App **не проксирует** payload — получает
  от backend только список deeplink-URL-ов и показывает QR + кнопки
  импорта. Это держит sub-Worker единственной edge-поверхностью для
  VPN-клиентов.
- **Deeplink схемы импорта** (фиксируем):
  - v2rayNG: `v2rayng://install-sub/?url=<urlencoded>&name=Vlessich`
  - Clash Meta / Stash: `clash://install-config?url=<urlencoded>&name=Vlessich`
  - sing-box (SFA): `sing-box://import-remote-profile?url=<urlencoded>&name=Vlessich`
  - Surge: `surge:///install-config?url=<urlencoded>`
  - Raw: copy plain URL.
- **QR-библиотека** = `qrcode.react` (~8KB, без доп. deps, MIT).
  Alternative (`react-qr-code`) отвергнут: использует `qr.js` с
  большими polyfill'ами.
- **State management** = **локальные хуки + `swr`** (`~4KB`). Один
  глобальный `SWRConfig` с `dedupingInterval=30s`, `revalidateOnFocus=true`.
  Alternative (TanStack Query) отвергнут: для 3 эндпоинтов избыточно.
- **Optimistic updates** для toggle routing — SWR `mutate(key, fn,
  { optimisticData, rollbackOnError: true })`.
- **Error boundary** — глобальный ErrorBoundary (class component) +
  Suspense для route-level lazy пока **не делаем** (3 страницы, бандл
  маленький). Lazy добавим при росте.
- **Skeleton-компоненты** = CSS `@keyframes shimmer` (без внешних
  deps).
- **Start-param extraction**: webapp читает `sub_token` из
  `window.Telegram.WebApp.initDataUnsafe.start_param` (параметр
  `?startapp=<token>` от бота — Stage 1 T7 уже шлёт). Fallback — URL
  query `?token=` для dev/браузерного превью.
- **Design.txt — строго**: Spotify Green **только** на primary CTA +
  active toggle state. Все buttons uppercase + letter-spacing
  1.4–2px. Cards 6–8px radius. Pills 9999px. Shadows heavy
  (`0 8px 24px rgba(0,0,0,0.5)` на modals/hover, `0 8px 8px rgba(0,0,0,0.3)`
  на cards).

---

## 0. Контекст

ТЗ §6 (Mini-App UX), §7 (sub-Worker), §11B (initData validation),
`Design.txt` (целиком). Цель — превратить scaffold webapp'а
(Stage 0 T10) в production-ready Spotify-dark Mini-App с рабочими
endpoints backend'а.

**Что НЕ делаем в этом этапе:**
- Admin UI (Stage 4).
- Node health / IP rotation (Stage 5).
- Observability / captcha (Stage 6).
- Платежи/покупка подписки из Mini-App — только отображение. Покупка
  остаётся в боте (Stage 1).
- i18n: только русский (TZ §6.1). Структура готовится для en/ru
  в будущем, но strings захардкожены в ru.

---

## 1. Definition of Done

- [ ] `POST /v1/webapp/*` и `GET /v1/webapp/*` endpoints требуют
      `x-telegram-initdata`, верификация HMAC-SHA256 + `auth_date` ≤ 24h.
- [ ] `GET /v1/webapp/bootstrap` возвращает `{user, subscription|null}`
      (snapshot для главного экрана).
- [ ] `GET /v1/subscription` возвращает `{sub_token, urls: {v2ray, clash,
      singbox, surge, raw}, devices: DeviceOut[], expires_at, plan, status}`.
- [ ] `POST /v1/subscription/toggle` body `{adblock?, smart_routing?}`
      персистит в БД + audit log.
- [ ] `POST /v1/devices/{id}/reset` перегенерирует `xray_uuid` +
      обновляет Remnawave + audit log.
- [ ] Webapp: 3 страницы (`/`, `/subscription`, `/routing`) работают
      с реальным backend'ом через SWR, имеют loading/error/empty states.
- [ ] Design-system компоненты переиспользуются: `PillButton`,
      `GhostButton`, `Card`, `Toggle`, `StatusBadge`, `CopyButton`,
      `QRCode`, `SkeletonBlock`.
- [ ] Strict Design.txt compliance: только allowed цвета, pill/circle
      геометрия, uppercase-кнопки, heavy shadows.
- [ ] Нет `as any`, `@ts-ignore`, `@ts-expect-error`, пустых `catch`.
- [ ] `tsc --noEmit` проходит локально (best-effort — без node
      верифицируем manual tsc-compliance).
- [ ] Vitest unit-тесты для: `lib/api.ts`, `components/*`,
      `hooks/useSubscription.ts` (тесты пишем, не запускаем).
- [ ] Backend unit-тесты для `auth/telegram.py` + `routers/webapp.py`
      (mock initData payload + signature).
- [ ] CHANGELOG → `[0.3.0]`.

---

## 2. Задачи (атомарные)

### T1 — Backend: `auth/telegram.py` initData verification

**Что:**
- `api/app/auth/telegram.py`:
  ```python
  class TelegramInitData(BaseModel):
      user_id: int
      username: str | None
      first_name: str | None
      auth_date: int
      start_param: str | None

  def verify_init_data(raw: str, bot_token: SecretStr, max_age_sec: int = 86400) -> TelegramInitData: ...
  ```
- Парсинг `raw` (URL-encoded query string): distinct fields, extract
  `hash`, собрать `data_check_string` = отсортированные `k=v` через `\n`.
- `secret_key = hmac.new(b"WebAppData", bot_token.get_secret_value().encode(), sha256).digest()`.
- `expected = hmac.new(secret_key, data_check_string.encode(), sha256).hexdigest()`.
- `hmac.compare_digest(expected, received_hash)` → иначе
  `HTTPException(401, {"code":"bad_init_data"})`.
- `now - auth_date > max_age_sec` → `HTTPException(401, {"code":"init_data_expired"})`.
- Парсим поле `user` (JSON) в `TelegramInitData`.
- `api/app/deps.py::get_init_data(x_telegram_initdata: Annotated[str, Header()])` dependency.
- `api/app/config.py`: убедиться что `api_bot_token: SecretStr` есть
  (он уже есть как `API_BOT_TOKEN`).
- Unit-тесты: valid data, bad hash, expired, missing fields, unknown
  user, malformed query.

**Commit:** `feat(api): telegram webapp init_data hmac verification`
**Effort:** 90 мин.

---

### T2 — Backend: `routers/webapp.py` — `GET /v1/webapp/bootstrap`

**Что:**
- `api/app/routers/webapp.py`:
  ```python
  router = APIRouter(prefix="/v1/webapp", tags=["webapp"])

  @router.get("/bootstrap", response_model=BootstrapOut)
  async def bootstrap(
      init: Annotated[TelegramInitData, Depends(get_init_data)],
      session: Annotated[AsyncSession, Depends(get_session)],
  ) -> BootstrapOut: ...
  ```
- Lookup `users WHERE tg_id=init.user_id` (create-if-missing **не
  делаем** — user создаётся ботом; возвращаем 404 если нет).
- Lookup active `subscriptions WHERE user_id=user.id AND status IN ('ACTIVE','TRIAL') ORDER BY created_at DESC LIMIT 1`.
- Response schema:
  ```python
  class BootstrapOut(BaseModel):
      user: UserOut  # {tg_id, username, first_name}
      subscription: SubscriptionSummary | None
  class SubscriptionSummary(BaseModel):
      id: UUID
      plan: str
      status: str
      expires_at: datetime
      adblock: bool
      smart_routing: bool
  ```
- 401 без initData, 404 если user не найден.
- Unit-тесты.

**Commit:** `feat(api): GET /v1/webapp/bootstrap endpoint`
**Effort:** 60 мин.

---

### T3 — Backend: `GET /v1/webapp/subscription` + sub-URL builder

**Что:**
- `api/app/services/sub_urls.py`:
  ```python
  def build_sub_urls(sub_token: str, base: str) -> dict[str, str]:
      return {
          "v2ray": f"{base}/{sub_token}?client=v2ray",
          "clash": f"{base}/{sub_token}?client=clash",
          "singbox": f"{base}/{sub_token}?client=singbox",
          "surge": f"{base}/{sub_token}?client=surge",
          "raw": f"{base}/{sub_token}?client=raw",
      }
  ```
- `settings.sub_worker_base_url: str` (например `https://sub.vlessich.example`).
- `GET /v1/webapp/subscription` → `{sub_token, urls, devices: [{id, label, last_ip_hash, created_at}], expires_at, plan, status, adblock, smart_routing}`.
- 404 если у user нет active sub (код `no_active_subscription`).
- Unit-тесты.

**Commit:** `feat(api): GET /v1/webapp/subscription with sub urls`
**Effort:** 60 мин.

---

### T4 — Backend: toggle routing + reset device

**Что:**
- `POST /v1/webapp/subscription/toggle` body
  `{adblock: bool | None, smart_routing: bool | None}` — хотя бы одно
  из полей должно быть указано, иначе 422. Обновляет
  `subscriptions.adblock`/`smart_routing`, `audit_log` event
  `webapp_toggle_routing`.
- `POST /v1/webapp/devices/{device_id}/reset`:
  - Lookup device, проверить `device.subscription.user_id == init.user_id` → иначе 403.
  - Сгенерировать новый `xray_uuid`, зашифровать через secretbox,
    `UPDATE devices SET xray_uuid = ...`.
  - Вызвать `remnawave.update_user_uuids(...)` (новый метод в ABC +
    обе реализации).
  - `audit_log` event `webapp_device_reset`.
  - Response: `{device_id, new_uuid_suffix: "****"+last4}` (полный UUID не отдаём).
- Rate-limit 5/min/user через sliding window.
- Unit-тесты: happy path, wrong owner 403, RL 429.

**Commit:** `feat(api): webapp toggle routing + device reset`
**Effort:** 120 мин.

---

### T5 — Webapp: design-system components

**Что:**
- `webapp/src/components/`:
  - `PillButton.tsx` — primary (green bg) / secondary (#1f1f1f bg) /
    ghost (transparent + outline); sizes `sm | md | lg`; uppercase +
    letter-spacing; loading state (spinner).
  - `Card.tsx` — `#181818` bg, 8px radius, optional shadow.
  - `Toggle.tsx` — pill-style switch; active = `#1ed760`; controlled.
  - `StatusBadge.tsx` — active (green) / expired (red) / trial (blue);
    uppercase 10.5px badge.
  - `CopyButton.tsx` — icon button, copy-to-clipboard + toast
    (inline ephemeral).
  - `QRCodeBlock.tsx` — wrapper `qrcode.react` с padding/bg=`#fff`
    (QR читается только на светлом).
  - `SkeletonBlock.tsx` — shimmer animation, accepts `w/h/radius`.
  - `CircularIconButton.tsx` — 50% radius, для play-like controls.
- Все компоненты — чистые презентационные, без data-fetch.
- Все — строго по Design.txt (никаких additional цветов).
- `webapp/src/components/index.ts` — barrel export.
- Vitest tests: рендер + snapshot + interaction (click).

**Commit:** `feat(webapp): spotify-dark design-system components`
**Effort:** 150 мин.

---

### T6 — Webapp: SWR config + api client + useSubscription hook

**Что:**
- `npm i swr qrcode.react` (добавить в `package.json`).
- `webapp/src/lib/api.ts`:
  - Добавить `getBootstrap()`, `getSubscription()`, `toggleRouting()`,
    `resetDevice(id)`.
  - Единый `fetcher(path, init?)` с auto-attach `x-telegram-initdata`
    из `window.Telegram.WebApp.initData`.
  - Typed DTOs (`BootstrapResponse`, `SubscriptionResponse`, etc.).
  - Error normalization: парсить `{code, message}` → `ApiError` class.
- `webapp/src/hooks/useSubscription.ts` — SWR wrapper с `keepPreviousData`.
- `webapp/src/hooks/useBootstrap.ts` — аналогично.
- `webapp/src/App.tsx` — wrap в `SWRConfig`.
- `webapp/src/lib/initData.ts` — helpers: `getInitData()`,
  `getStartParam()`, `getUser()` (все читают `window.Telegram.WebApp`,
  fallback `null`).
- Vitest tests: api client (mock fetch), SWR hook (mock fetcher).

**Commit:** `feat(webapp): swr + api client + initData helpers`
**Effort:** 90 мин.

---

### T7 — Webapp: `pages/Home.tsx` rewrite

**Что:**
- Заменить placeholder на реальный экран:
  - Header: `VLESSICH` wordmark + `StatusBadge` (active/trial/expired).
  - Hero card: план + «действует до DD.MM.YYYY» + остаток дней.
  - 3 `PillButton` CTA: `ПОКАЗАТЬ ПОДПИСКУ` (→ `/subscription`),
    `НАСТРОИТЬ МАРШРУТИЗАЦИЮ` (→ `/routing`),
    `ПОЛУЧИТЬ MTPROTO` (→ deep-link `https://t.me/<bot>?start=mtproto`).
  - Empty state (нет подписки): `Card` с текстом + CTA `ОТКРЫТЬ БОТА`
    (`https://t.me/<bot>?start=buy`).
  - Loading: 3 `SkeletonBlock`.
  - Error: `Card` с сообщением + retry button.
- Данные через `useBootstrap()`.

**Commit:** `feat(webapp): home page with real bootstrap data`
**Effort:** 90 мин.

---

### T8 — Webapp: `pages/Subscription.tsx` rewrite

**Что:**
- Экран:
  - `Card` с QR code (по умолчанию = raw URL) + `CopyButton` на URL.
  - 4 секции импорта (v2rayNG/Clash/sing-box/Surge): каждая — `Card`
    с логотипом (unicode emoji placeholder — без assets пока),
    `PillButton` «ОТКРЫТЬ В <CLIENT>» с deeplink URL.
  - Devices list (если есть): `Card` per device — label + last_ip_hash
    shortened + `GhostButton` «СБРОСИТЬ» → confirmation modal →
    `resetDevice(id)` + SWR revalidate.
  - Copy-toast (3s).
- Error boundary обёртка.
- Данные через `useSubscription()`.

**Commit:** `feat(webapp): subscription page with qr + deeplinks + device reset`
**Effort:** 150 мин.

---

### T9 — Webapp: `pages/Routing.tsx` rewrite + optimistic toggles

**Что:**
- Два `Card`:
  - **Adblock** — `Toggle` + описание «Блокирует рекламу и трекеры через AGH DNS».
  - **Smart routing** — `Toggle` + описание «Российские сайты через локального провайдера, остальное — через VPN».
- `onToggle` → SWR `mutate('/v1/webapp/subscription', optimistic, rollbackOnError)`.
- Loading skeleton при init.
- Error toast при rollback.
- Vitest tests на компонент (mock SWR).

**Commit:** `feat(webapp): routing page with optimistic toggles`
**Effort:** 90 мин.

---

### T10 — Docs + CHANGELOG + README

**Что:**
- CHANGELOG `## [0.3.0] - 2026-04-xx` с T1-T9.
- `docs/ARCHITECTURE.md`: раздел «Mini-App ↔ Backend contract»
  (initData HMAC flow, `/v1/webapp/*` таблица, sub-URL builder).
- `webapp/README.md`: обновить структуру (`components/`, `hooks/`),
  добавить Design.txt compliance checklist.
- `README.md`: отметить Mini-App endpoints как implemented.

**Commit:** `docs: stage-3 miniapp + backend webapp contract`
**Effort:** 30 мин.

---

## 3. Порядок исполнения

```
T1 (initData verify)    → базовый, первым
T2 (bootstrap)          → после T1
T3 (subscription)       → после T1
T4 (toggle + reset)     → после T3
T5 (components)         → параллельно T1-T4
T6 (swr + api)          → после T5 (нужен typed client)
T7 (Home)               → после T2, T5, T6
T8 (Subscription)       → после T3, T5, T6
T9 (Routing)            → после T4, T5, T6
T10 (docs)              → последним
```

---

## 4. Риски и митигации

| Риск | Митигация |
|---|---|
| `window.Telegram.WebApp` отсутствует вне TG (dev-превью) | Fallback: query `?initData=...` для локальной разработки, предупреждение в `<DevBanner/>` |
| initData HMAC не совпадает из-за URL encoding | Парсить через `URLSearchParams` (native), не делать лишнего decode на `data_check_string` |
| QR unreadable из-за dark theme | QR контейнер ВСЕГДА на белом bg (#fff) с 16px padding (TZ исключение: Design.txt разрешает album-art как «content color» — QR = content) |
| Deeplink v2rayNG/Clash schemes меняются | Хранить шаблоны в `webapp/src/lib/deeplinks.ts` — один source of truth |
| SWR + StrictMode двойной fetch в dev | Acceptable; prod без StrictMode |
| Нет node → нельзя проверить `tsc` | Manual tsc-compliance через чтение файлов + строгий review перед коммитом |
| `qrcode.react` несовместим с React 18 strict | Проверить версию (`^3.x` совместима) |
| `bot_token` в dev `.env.dev` отсутствует | Тесты используют hardcoded `"TEST_BOT_TOKEN"`; в dev выдаётся 401 с явным `code: "bot_token_not_configured"` |

---

## 5. Out of scope (→ Stage 4+)

- Admin UI (Stage 4).
- Node health / IP rotation (Stage 5).
- Observability / captcha (Stage 6).
- Покупка подписки из Mini-App (остаётся в боте).
- i18n en/ru switching (только ru пока).
- Push-уведомления из webapp.

---

## 6. Non-negotiables check-list

- [ ] Design.txt strict: Spotify Green ТОЛЬКО на primary CTA + active toggle.
- [ ] Нет `as any`, `@ts-ignore`, `@ts-expect-error`, `# type: ignore`, пустых `catch (e) {}`.
- [ ] Все API ошибки формата `{code, message}`.
- [ ] initData HMAC verify — constant-time compare.
- [ ] Никаких sensitive данных в логах (full xray_uuid, initData hash).
- [ ] Все pydantic/zod DTO на границе.
- [ ] Audit log на toggle + reset.
- [ ] Sub-URL не попадают в логи frontend (только в console.error на dev).
- [ ] Rate-limit на reset-device (5/min/user).
- [ ] Mini-App bundle ≤ 200KB gzip (SWR + qrcode.react + React ~160KB).
- [ ] Tests написаны (но не запущены).
