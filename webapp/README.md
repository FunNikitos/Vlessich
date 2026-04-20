# Vlessich — Mini-App (webapp)

React 18 + Vite + TypeScript + TailwindCSS + Telegram Apps SDK.
Дизайн строго по `Design.txt` (Spotify-dark).

## Dev

```bash
cp .env.example .env
npm install
npm run dev   # http://localhost:5173
```

## Структура

```
src/
  App.tsx              — router shell
  main.tsx             — bootstrap
  index.css            — tailwind + Spotify-pill components
  hooks/useTelegram.ts — TG WebApp init + theme apply
  lib/api.ts           — backend client (initData header)
  pages/Home.tsx       — главная (план/сроки)
  pages/Subscription.tsx
  pages/Routing.tsx
```

## Build

```bash
npm run build
docker build -t vlessich-webapp .
```

В прод деплой — Cloudflare Pages (см. `infra/cloudflare.tf`).
