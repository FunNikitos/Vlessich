# Vlessich — Mini-App (webapp)

React 18 + Vite + TypeScript + TailwindCSS + SWR + Telegram Apps SDK.
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
  App.tsx                    — router shell + SWRConfig
  main.tsx                   — bootstrap
  index.css                  — tailwind + Spotify-pill components + shimmer
  hooks/
    useTelegram.ts           — TG WebApp init + theme apply
    useBootstrap.ts          — SWR: GET /v1/webapp/bootstrap
    useSubscription.ts       — SWR: GET /v1/webapp/subscription
  lib/
    api.ts                   — typed backend client (initData header)
    initData.ts              — helpers (initData, start_param, user)
    deeplinks.ts             — v2rayNG/Clash/sing-box/Surge schemes
  components/
    PillButton.tsx           — Spotify pill (primary/secondary/ghost)
    Card.tsx                 — #181818 surface + optional shadow
    Toggle.tsx               — brand-green active switch
    StatusBadge.tsx          — 10.5px uppercase pill badge
    CopyButton.tsx           — clipboard + 2s feedback
    QRCodeBlock.tsx          — white-bg QR (qrcode.react)
    SkeletonBlock.tsx        — shimmer loading placeholder
  pages/
    Home.tsx                 — план + expiry + CTA
    Subscription.tsx         — QR + deeplinks + devices
    Routing.tsx              — adblock + smart_routing toggles
```

## Design.txt compliance checklist

- ✅ Background `#121212`, surfaces `#181818`/`#1f1f1f`
- ✅ Spotify Green `#1ed760` только на primary CTA + active toggle
- ✅ Pill 9999px radius на всех кнопках
- ✅ Uppercase + letter-spacing 1.4–2px на кнопках и метках
- ✅ Heavy shadow `0 8px 24px rgba(0,0,0,0.5)` на elevated cards
- ✅ Bold/regular binary typography (700/400)
- ✅ Нет decorative зелёного, нет дополнительных brand цветов

## Build

```bash
npm run build
docker build -t vlessich-webapp .
```

В прод деплой — Cloudflare Pages (см. `infra/cloudflare.tf`).
