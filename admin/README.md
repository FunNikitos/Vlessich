# Vlessich — Admin Panel

React 18 + Vite + TypeScript + TailwindCSS + TanStack Query v5.
Spotify-dark по [`Design.txt`](../Design.txt) — строго: Spotify Green
(#1ed760) только для primary CTA и активной навигации, `bg-base` #121212,
`bg-elevated` #181818, uppercase + letter-spacing 1.4–2px.

## Аутентификация

JWT Bearer через `POST /admin/auth/login` (email + password, HS256, TTL
1h). Токен хранится в `sessionStorage` под ключом `vlessich.admin.jwt`
(не `localStorage` — меньше persistence risk). На `401` — автоматический
redirect на `/login`.

### RBAC

| Роль | Rank | Что может |
|---|---|---|
| `superadmin` | 3 | Всё: create/edit/revoke codes, nodes, subscriptions |
| `support` | 2 | Revoke subscriptions, create codes, read-only остальное |
| `readonly` | 1 | Только чтение |

Enforced на backend (`require_admin_role(*roles)`); фронт дополнительно
скрывает недоступные кнопки.

## Dev

```bash
cp .env.example .env
npm install
npm run dev   # http://localhost:5174
```

`.env`:
```
VITE_API_BASE_URL=http://localhost:8000
# Optional: Cloudflare Turnstile sitekey. Empty = no captcha widget.
VITE_TURNSTILE_SITEKEY=
```

Для прода собрать статику и отдать через nginx / Cloudflare Pages за
Access-политикой:
```bash
npm run build
```

## Страницы

- `/` **Dashboard** — node health panel (HEALTHY/BURNED/MAINTENANCE/STALE
  tiles + stacked bar) + 6 metric cards (users, subs active/trial, codes,
  nodes). Auto-refresh 30s.
- `/codes` **Codes** — фильтры (status / plan / tag), pagination, batch
  create (one-time plaintext display + "copy all"), revoke (superadmin,
  "type REVOKE" confirm).
- `/users` **Users** — фильтр по `tg_id`, link → subscriptions.
- `/subscriptions` **Subscriptions** — фильтры (status / plan /
  `user_id` из URL), revoke с confirm (support+).
- `/audit` **Audit log** — фильтры (action, actor_type), expandable
  JSON payload.
- `/nodes` **Nodes** — list, create/edit (superadmin), **health drawer**
  (uptime 24h, p50/p95 latency, sparkline + probe log).

## Design-system inventory

`src/components/`:
`PillButton`, `Card`, `Table<T>`, `Pagination`, `Modal`, `Drawer`,
`FormField`, `Input`, `Select`, `Textarea`, `StatusBadge`, `RoleBadge`,
`Toggle`, `SkeletonBlock`, `Sparkline`, `PageHeading`,
`CreateCodesModal`, `ConfirmDestructiveModal`, `CreateNodeModal`,
`EditNodeModal`, `NodeHealthDrawer`, `AppShell`, `ProtectedRoute`.

## TanStack Query keys (convention)

```
["stats"]
["codes", { status, plan, tag, page }]
["users", { tg_id, page }]
["subs",  { status, plan, user_id, page }]
["audit", { action, actor_type, page }]
["nodes"]
["node-health", id]
```

## Тесты

```bash
npm run test   # vitest + jsdom
```

Покрытие: auth store, api client, login page.

## Non-negotiables

- Никаких `as any`, `@ts-ignore`, `@ts-expect-error`, пустых `catch {}`.
- Dark only — никакого light-theme.
- JWT только в `sessionStorage`, никогда в `localStorage` / cookies.
- Все destructive actions — через `ConfirmDestructiveModal`.
