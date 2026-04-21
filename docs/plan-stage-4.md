# Stage 4 — Admin UI (React + JWT + Spotify-dark)

**Версия:** 1.0
**Дата:** 21.04.2026
**Статус:** ⏳ pending approval
**Предпосылка:** Stage 3 завершён (ветка `feat/stage-3-miniapp`, HEAD `0201ccb`).
**Ветка:** `feat/stage-4-admin-ui` (создана от `feat/stage-3-miniapp`).
**Срок:** ~16–20 часов работы.

## Утверждённые решения (locked)

- **Authn admin → backend** = **JWT Bearer** через `POST /admin/auth/login`
  (уже существует с Stage 2 T4). Form = `{email, password}`. Backend
  возвращает `{access_token, role}`. TTL 1h (`settings.admin_jwt_ttl_sec`).
- **JWT storage** = **sessionStorage** (`vlessich.admin.jwt`). Очищается
  при закрытии вкладки → меньше XSS-риск. На 401 → redirect `/login`.
  Refresh endpoint — **не делаем** в Stage 4 (user перелогинится).
- **State management** = **TanStack Query v5** (уже в scaffold).
  Query keys: `["codes", filters]`, `["users", filters]`, `["subs", filters]`,
  `["audit", filters]`, `["nodes"]`, `["stats"]`. Mutations с
  `invalidateQueries`.
- **Routing** = `react-router-dom` v6 (уже scaffolded). Новые route:
  `/login`, `/subscriptions`, `/audit`. `/`, `/codes`, `/users`, `/nodes`
  остаются. `<ProtectedRoute>` wrapper проверяет JWT + срок + роль.
- **RBAC UI** — скрывать элементы по `role`:
  - `readonly` — видит всё read-only; нет create/delete/patch UI.
  - `support` — + create codes, revoke subscriptions.
  - `superadmin` — + delete codes, create/patch nodes.
- **Форма генерации codes** — модалка с batch-полями `{plan, duration_days,
  devices, count, valid_days, tag?, note?}`. После создания — **один раз**
  показать plaintexts в monospace-блоке с `CopyAll` кнопкой и warning
  "Сохраните сейчас — повторно не покажутся".
- **Revoke flow** — двухступенчатая конфирмация: кнопка → modal
  `type REVOKE to confirm` → mutation.
- **Design.txt — строго**: Spotify Green только на primary CTA + active nav.
  Tables — `#181818` header, `#121212` body, row hover `#1f1f1f`.
  Pagination — pill-кнопки. Все buttons uppercase + letter-spacing 1.4–2px.
- **Backend additions (T1)**:
  - `GET /admin/stats` → `{users_total, codes_total, codes_unused,
    subs_active, subs_trial, nodes_active}` (RBAC: any authenticated).
  - `POST /admin/subscriptions/{id}/revoke` → переводит в `REVOKED` +
    `audit_log` (RBAC: support+).
- **QR / deeplink logic** — **не переносим**, это webapp-specific.

---

## 0. Контекст

ТЗ §10 (Admin panel), §11A (auth — для Stage 4 backend уже имеет свой JWT),
`Design.txt`. Цель — превратить scaffold admin-панели (Stage 0 T10) в
production-ready Spotify-dark UI для управления codes / users /
subscriptions / audit / nodes c JWT-auth и RBAC.

**Что НЕ делаем в этом этапе:**
- Node health dashboard / IP rotation UI (Stage 5).
- Captcha / observability (Stage 6).
- Admin CRUD для users (только read).
- Bulk операции (bulk revoke и т.п.).
- i18n — пока только ru (хардкод strings).
- 2FA / TOTP.
- Refresh-token flow.

---

## 1. Definition of Done

- [ ] `GET /admin/stats` + `POST /admin/subscriptions/{id}/revoke` реализованы
      с RBAC + audit.
- [ ] Admin UI требует JWT; на 401 редиректит на `/login`.
- [ ] Форма логина работает: `POST /admin/auth/login` → сохраняет токен +
      роль в sessionStorage → redirect `/`.
- [ ] RBAC visibility: UI элементы скрыты/disabled по роли.
- [ ] `/codes`: list с фильтрами (status, plan) + pagination, создание
      batch + one-time plaintext display, revoke confirm (superadmin).
- [ ] `/users`: list с фильтром по `tg_id` + pagination.
- [ ] `/subscriptions`: list с фильтрами (status, plan, user_id) +
      pagination + revoke (support+).
- [ ] `/audit`: list с фильтрами (action, actor_type) + pagination.
- [ ] `/nodes`: list + create + patch (status/IP) (superadmin).
- [ ] `/`: Dashboard с 6 metric cards (из `/admin/stats`).
- [ ] Design-system компоненты: `PillButton`, `Card`, `Table`,
      `Pagination`, `Modal`, `FormField`, `Select`, `Input`, `Textarea`,
      `StatusBadge`, `RoleBadge`, `Toggle`, `SkeletonRow`.
- [ ] Strict Design.txt compliance: Spotify-dark only, pill/uppercase.
- [ ] Нет `as any`, `@ts-ignore`, `@ts-expect-error`, пустых `catch`.
- [ ] Vitest unit-тесты для `lib/auth.ts`, `lib/api.ts`, ключевых
      компонентов (`Table`, `Pagination`, `Modal`) и pages smoke-render.
- [ ] Backend pytest для новых endpoints (`/admin/stats`, revoke).
- [ ] CHANGELOG → `[0.4.0]`.
- [ ] Admin README переписан (убрать устаревший Cloudflare Access, описать
      JWT login).
- [ ] ARCHITECTURE.md §15 — Admin UI contract.

---

## 2. Задачи (атомарные)

### T1 — Backend: `GET /admin/stats` + `POST /admin/subscriptions/{id}/revoke`

**Что:**
- `api/app/routers/admin/views.py`:
  ```python
  @router.get("/stats", response_model=StatsOut)
  async def stats(
      actor: Annotated[AdminActor, Depends(require_role("readonly"))],
      session: Annotated[AsyncSession, Depends(get_session)],
  ) -> StatsOut: ...
  ```
  - COUNT(*) users, codes, codes WHERE status='unused', subs
    WHERE status='ACTIVE', subs WHERE status='TRIAL', nodes
    WHERE status='active'.
  - `StatsOut`: `{users_total, codes_total, codes_unused, subs_active,
    subs_trial, nodes_active}` — все `int`.
- `api/app/routers/admin/subscriptions.py` (новый модуль или в существующий
  views.py) — `POST /admin/subscriptions/{sub_id}/revoke` (RBAC `support`+):
  - Lookup sub, 404 если нет.
  - Если `status IN ('REVOKED','EXPIRED')` → 409 `already_inactive`.
  - `UPDATE subscriptions SET status='REVOKED', revoked_at=now()`.
  - `audit_log` event `admin_subscription_revoke`
    `{actor, subscription_id, user_id, plan, previous_status}`.
  - Response `SubscriptionOut` (новое/существующее DTO).
- `api/app/errors.py`: код `already_inactive`, `subscription_not_found`.
- `api/app/schemas.py`: `StatsOut`.
- Unit-тесты: happy path, 403 для `readonly` на revoke, 404, 409,
  audit-log написан.

**Commit:** `feat(api): admin stats + subscription revoke`
**Effort:** 90 мин.

---

### T2 — Admin: design-system components

**Что:**
- `admin/src/components/`:
  - `PillButton.tsx` — primary/secondary/ghost/danger variants;
    sizes `sm | md | lg`; uppercase + letter-spacing 1.6px; loading spinner.
  - `Card.tsx` — `#181818` bg, 8px radius, optional title + shadow.
  - `Table.tsx` — generic `<T>`: `columns: {key, label, render}[]`,
    `rows: T[]`, `loading?`, `empty?`. Header `#181818`, row hover
    `#1f1f1f`, 13px body text.
  - `Pagination.tsx` — `{page, total, limit, onChange}`. Pill-кнопки
    `< 1 2 3 >`, center ellipsis.
  - `Modal.tsx` — portal, backdrop blur, esc to close, focus trap.
    `{open, onClose, title, children, actions?}`.
  - `FormField.tsx` — `{label, error?, children, hint?}`, spacing и typography
    унифицированы.
  - `Input.tsx`, `Select.tsx`, `Textarea.tsx` — `#1f1f1f` bg, 1px border
    transparent, focus border `#1ed760`.
  - `StatusBadge.tsx` — `active/trial/expired/revoked/unused/used`
    → разные цвета.
  - `RoleBadge.tsx` — `superadmin` (green) / `support` (blue) /
    `readonly` (gray).
  - `Toggle.tsx` — как в webapp.
  - `SkeletonRow.tsx` — shimmer ряд для Table.
- `admin/src/components/index.ts` barrel.
- `admin/src/index.css` — утилиты `.btn-pill`, `.card`, `.badge`, если
  нужны.
- Vitest: render + basic interaction для `PillButton`, `Table`,
  `Pagination`, `Modal`.

**Commit:** `feat(admin): spotify-dark design-system components`
**Effort:** 150 мин.

---

### T3 — Admin: auth (lib/auth + api client + AuthContext)

**Что:**
- `admin/src/lib/auth.ts`:
  ```ts
  type Role = "superadmin" | "support" | "readonly";
  type StoredAuth = { token: string; role: Role; email: string; exp: number };
  const KEY = "vlessich.admin.jwt";

  export const authStore = {
    get(): StoredAuth | null,
    set(a: StoredAuth): void,
    clear(): void,
    isExpired(a: StoredAuth): boolean,
  };

  export function decodeJwt(token: string): { sub: string; role: Role; exp: number };
  export function hasRole(actual: Role, required: Role): boolean; // superadmin > support > readonly
  ```
- `admin/src/lib/api.ts` — переписать:
  - Убрать `credentials: "include"`.
  - Attach `Authorization: Bearer <token>` из `authStore.get()`.
  - 401 → `authStore.clear()` + `window.location.assign("/login")`.
  - Типизированные DTO (импорт из `lib/types.ts`).
  - Endpoints: `login`, `stats`, `codes.list`, `codes.create`,
    `codes.revoke`, `users.list`, `subs.list`, `subs.revoke`,
    `audit.list`, `nodes.list`, `nodes.create`, `nodes.patch`.
- `admin/src/lib/types.ts` — DTO mirrors backend (`CodeOut`, `UserOut`,
  `SubscriptionOut`, `AuditEntryOut`, `NodeOut`, `StatsOut`, `LoginOut`,
  `Role`, enums).
- `admin/src/hooks/useAuth.tsx` — `<AuthProvider>` + `useAuth()` hook
  с `{auth, login, logout}`. Init из `authStore`, auto-logout на expiry
  через `setTimeout`.
- Vitest: `authStore` (set/get/clear/isExpired), `hasRole` RBAC logic,
  `api.request` с mock fetch (401 redirect mocked).

**Commit:** `feat(admin): jwt auth store + typed api client + auth context`
**Effort:** 120 мин.

---

### T4 — Admin: Login page + ProtectedRoute + App shell

**Что:**
- `admin/src/pages/Login.tsx`:
  - Centered card `max-w-sm`.
  - `FormField` email, `FormField` password, `PillButton` primary
    "SIGN IN".
  - On submit → `api.login({email, password})` → `authStore.set(...)` →
    `navigate("/")`.
  - Error inline ("Неверные данные" / "Rate limited" / network).
- `admin/src/components/ProtectedRoute.tsx`:
  - Если `authStore.get()` нет или expired → `<Navigate to="/login" replace />`.
  - Если `requiredRole` передан и `!hasRole(auth.role, requiredRole)` →
    рендерит `<ForbiddenPage />`.
- `admin/src/App.tsx` — переписать:
  - Routes:
    - `/login` → `<LoginPage />`
    - `/*` (остальное) → `<ProtectedRoute><AppShell /></ProtectedRoute>`
  - `AppShell`: sidebar `Vlessich · Admin` + email + `RoleBadge` +
    logout (`PillButton ghost` SIGN OUT). NavItems видимы по роли:
    Dashboard (all), Codes (all), Users (all), Subscriptions (all),
    Audit (all), Nodes (all).
- Smoke vitest: render Login, submit dispatches api.login.

**Commit:** `feat(admin): login page + protected route + app shell`
**Effort:** 90 мин.

---

### T5 — Admin: Codes page (list + filters + pagination)

**Что:**
- `admin/src/pages/Codes.tsx`:
  - Header: `CODES` title + `PillButton primary "+ CREATE BATCH"`
    (disabled если role=readonly).
  - Filters row: `Select status` (all/unused/used/revoked),
    `Select plan` (all/7d/30d/180d/year), `Input search tag` (debounced).
  - `Table` columns: `code_preview` (`****` + last 4 decrypted? — нет,
    показываем `tag` + `id[:8]`), `plan`, `duration_days`, `devices`,
    `status`, `tag`, `created_at`, actions (revoke — только superadmin).
  - `Pagination` внизу.
  - useQuery key `["codes", {status, plan, tag, page}]`.
  - Empty state.
- Backend filters — всё уже есть в `GET /admin/codes`.

**Commit:** `feat(admin): codes list with filters + pagination`
**Effort:** 90 мин.

---

### T6 — Admin: Codes create-batch modal + revoke flow

**Что:**
- `admin/src/components/CreateCodesModal.tsx`:
  - Form: `Select plan`, `Input duration_days` (number), `Input devices`
    (1..5), `Input count` (1..500), `Input valid_days` (1..365),
    `Input tag?`, `Textarea note?`.
  - Zod-like inline validation.
  - Submit → `api.codes.create(body)` → response `{created, codes: string[]}`.
  - После успеха — **сменить UI модалки** на "Generated N codes" +
    monospace block с плейнтекстами (один под другим), `CopyAll` button,
    warning "Сохраните — повторно НЕ покажутся", `DONE` button.
  - `invalidateQueries(["codes"])` + `invalidateQueries(["stats"])`.
- `admin/src/components/RevokeConfirmModal.tsx`:
  - "Type `REVOKE` to confirm" input.
  - Disabled до точного совпадения.
  - Mutation → `api.codes.revoke(id)` → invalidate.
- Vitest: form validation, two-phase modal flow.

**Commit:** `feat(admin): codes batch create + revoke modal`
**Effort:** 120 мин.

---

### T7 — Admin: Users + Subscriptions pages

**Что:**
- `admin/src/pages/Users.tsx`:
  - Filter: `Input tg_id` (numeric, debounced).
  - `Table`: `tg_id`, `username`, `first_name`, `created_at`, actions
    (View → navigate `/subscriptions?user_id=<uuid>`).
  - `Pagination`.
- `admin/src/pages/Subscriptions.tsx` (новая):
  - Filters: `Select status`, `Select plan`, `Input user_id` (uuid,
    preset из query).
  - `Table`: `id[:8]`, `user.tg_id`, `plan`, `status` (StatusBadge),
    `expires_at`, `adblock` (✓/—), `smart_routing` (✓/—), `created_at`,
    actions (Revoke — support+).
  - Revoke — `RevokeConfirmModal` (reused).
  - `Pagination`.
- Добавить route в App: `/subscriptions`.
- Добавить NavItem.

**Commit:** `feat(admin): users + subscriptions pages with filters`
**Effort:** 120 мин.

---

### T8 — Admin: Audit + Nodes pages

**Что:**
- `admin/src/pages/Audit.tsx`:
  - Filters: `Select action` (whitelist констант), `Select actor_type`
    (admin/system/user/bot).
  - `Table`: `created_at`, `actor_type`, `actor_label`, `action`,
    `target`, `meta_preview` (truncate JSON).
  - Row click → expand `<details>` с full JSON.
  - `Pagination`.
- `admin/src/pages/Nodes.tsx`:
  - Заголовок + `PillButton primary "+ ADD NODE"` (superadmin).
  - `Table`: `hostname`, `ip`, `status` (StatusBadge), `region`,
    `last_health_at`, actions (Edit — superadmin).
  - `CreateNodeModal` — form `{hostname, ip, region, status?}`.
  - `EditNodeModal` — patch `{status, ip}`.
  - Mutations invalidate `["nodes"]` + `["stats"]`.

**Commit:** `feat(admin): audit + nodes pages with mutations`
**Effort:** 120 мин.

---

### T9 — Admin: Dashboard with stats metrics

**Что:**
- `admin/src/pages/Dashboard.tsx`:
  - `useQuery(["stats"], api.stats)`.
  - 6 `Card` metric tiles в grid `lg:grid-cols-3`:
    - `USERS TOTAL` (big number)
    - `SUBS ACTIVE`
    - `SUBS TRIAL`
    - `CODES UNUSED / TOTAL` (`42 / 150`)
    - `NODES ACTIVE`
    - `LAST LOGIN` — из `auth` (формат `dd.MM HH:mm`) [client-side only]
  - Каждая Card: uppercase label 11px + number 32px font-bold +
    footer hint.
  - Loading = `SkeletonBlock` для чисел.
  - Error banner с retry `PillButton`.
- Auto-refresh `refetchInterval: 30_000`.

**Commit:** `feat(admin): dashboard with stats metrics`
**Effort:** 60 мин.

---

### T10 — Docs: CHANGELOG + README + ARCHITECTURE

**Что:**
- `CHANGELOG.md`: `[0.4.0] — 2026-04-22` с блоками Added/Changed/
  Security (админ JWT в sessionStorage, RBAC UI).
- `admin/README.md` — переписать:
  - Убрать упоминания Cloudflare Zero Trust Access.
  - Описать JWT login flow (POST /admin/auth/login → sessionStorage).
  - Pages: `/login`, `/`, `/codes`, `/users`, `/subscriptions`,
    `/audit`, `/nodes`.
  - RBAC таблица (what each role sees).
  - `npm run dev` → :5174, env `VITE_API_BASE_URL`.
- `docs/ARCHITECTURE.md` §15 — Admin UI:
  - Stack, auth model, RBAC matrix, query-key conventions,
    design-system inventory.
- `README.md` (root) — обновить API surface таблицу (`/admin/stats`,
  `/admin/subscriptions/{id}/revoke`).
- Verification:
  - AST parse всех изменённых `.py`.
  - `ast-grep` `# type: ignore` / `as any` / `@ts-ignore` / пустые catch
    в `admin/src/`.

**Commit:** `docs: stage-4 admin ui + backend additions`
**Effort:** 60 мин.

---

## 3. Верификация (manual, без node)

- AST parse всех новых `.py` в `api/app/routers/admin/` и
  `api/app/schemas.py`, `errors.py`.
- AST-aware `# type: ignore` grep → 0 executable hits.
- `admin/src/` — `ast-grep` patterns:
  - `as any` (TS) → 0
  - `@ts-ignore` / `@ts-expect-error` → 0
  - `catch ($_) { }` (empty) → 0
- TSC-compliance review: все props/DTO типизированы, no `any`,
  generic Table типизирован.
- Design.txt audit: grep Tailwind classes на запрещённые цвета
  (`text-blue-`, `bg-red-` и т.п. вне allow-list токенов).
- `docker-compose config` → OK (без изменений сервисов).

---

## 4. Риски / заметки

- **JWT в sessionStorage** — XSS остаётся риском; mitigation в Stage 6
  (CSP + helmet на admin). Refresh flow — Stage 6 или позже.
- **Без `npm install`** — все TS типы и пакеты (`@tanstack/react-query`,
  `react-router-dom`) уже в `package.json` из Stage 0; новых deps не
  добавляем.
- **Codes plaintext one-time display** — backend уже возвращает их в
  response только на create; re-fetch не показывает. Консистентно.
- **Revoke subscriptions** — добавит nullable `revoked_at` column,
  если его ещё нет. Проверить в T1 (migration).
- **GET /admin/codes возвращает encrypted `code_preview`** — на UI
  показываем `tag` + `id[:8]`, не plaintext.

---

**Effort total:** ~16 часов (без учёта overhead на verify + docs).
