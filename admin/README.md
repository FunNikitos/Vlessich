# Vlessich — Admin Panel

React 18 + Vite + TS + TailwindCSS + TanStack Query.
Spotify-dark по `Design.txt`. Доступ — через Cloudflare Zero Trust Access
(см. `infra/cloudflare.tf`), без локальной auth-логики.

## Dev

```bash
cp .env.example .env
npm install
npm run dev   # http://localhost:5174
```

## Pages
- `/` Dashboard (метрики)
- `/codes` Codes (генерация, отзыв)
- `/users` Users
- `/nodes` Nodes (health, BURNED, ротация)

Backend endpoints (`/admin/*`) — TODO в `api/`.
