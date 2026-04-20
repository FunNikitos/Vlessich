# ТЗ: Telegram-бот «Vlessich» — VPN-as-a-Service для РФ

**Версия:** 1.3 (финальная, консолидированная)
**Дата:** 20.04.2026
**Исполнитель:** ИИ-программист (Claude/GPT/Cursor) или senior full-stack dev
**Срок MVP:** 2–3 недели, полный релиз v1.0 — 4–5 недель
**Локация сервера:** Финляндия (Helsinki)
**Дизайн-система:** см. `Design.txt` (Spotify-dark)

---

## 0. TL;DR — что строим за одну минуту

Telegram-бот + Mini-App + админ-панель + Финская VPN-нода. Пользователь либо получает **3-дневный триал** по кнопке, либо вводит **код активации**, который админ генерит в панели после оплаты в личке. VPN-протокол — **VLESS + Reality + XTLS-Vision** (основной) и **Hysteria2** (резерв) на одной ноде в FI. Дополнительно бот выдаёт **MTProto-прокси для самого Telegram** (на случай блокировки мессенджера в РФ). Умный роутинг: RU-сервисы идут напрямую, остальной трафик — через VPN. Реклама блокируется через AdGuard Home. Дизайн — строго Spotify-dark по `Design.txt` (near-black + зелёный акцент #1ed760, pill-кнопки, uppercase лейблы).

---

## 1. Цели и принципы

1. **Стабильная работа в РФ против ТСПУ** в 2025–2026 гг.
2. **Оплата вне системы** — модель «код активации». Никаких встроенных платёжек в MVP.
3. **Триал 3 дня** при первом входе — без карты, без лишних шагов.
4. **Smart-routing** (split-tunneling): трафик к российским сервисам — direct, остальное — через VPN.
5. **Блокировка рекламы** на уровне DNS внутри туннеля.
6. **Админ-панель** с генерацией ключей, статистикой, батч-операциями, anti-fraud.
7. **Премиум UX** в боте и Mini-App (Spotify-dark, pill-кнопки, карточки).
8. **Максимальная защита инфраструктуры**: маскировка, стелс, авто-ротация IP, honeypots.
9. **High-performance**: ≥600 Mbps single-stream, ≥900 Mbps multi-stream на гигабитной ноде.

---

## 2. Протокольный стек (обоснование)

### 2.1. Сравнение (2025–2026)

| Протокол / Transport | ТСПУ-устойчивость | Скорость | Вердикт |
|---|---|---|---|
| OpenVPN / IKEv2 / L2TP | Заблокированы | средняя | Нет |
| WireGuard классический | Блокируется по handshake | очень высокая | Нет |
| Shadowsocks 2022 | Палится по энтропии | высокая | Только fallback |
| VMess / VLESS+TCP+TLS | Иногда режется | высокая | Условно |
| VLESS + Reality + XTLS-Vision (TCP) | ⚠️ на длинных флоу ТСПУ начал палить (2025 flow-pattern detection) | Очень высокая (zero-copy) | **Совместимость** |
| **VLESS + Reality + XHTTP (H2)** | ✅ Хорошо | Высокая | **Основной anti-DPI TCP** |
| **VLESS + Reality + XHTTP (H3 / QUIC)** | ✅✅ **Лучшее на апрель 2026** | Очень высокая | **Основной anti-DPI UDP** |
| **Hysteria2 (QUIC/UDP/443)** | ✅ Хорошо, UDP иногда шейпится | Максимальная (BBR) | **Резерв №1 для моб. операторов** |
| TUIC v5 | Похоже на Hysteria2 | высокая | Опционально |
| AmneziaWG | Хорошо | очень высокая | Опционально |

### 2.2. Финальный стек (4 inbound'а на одной ноде)

1. **VLESS + Reality + XHTTP (H3/QUIC)** — основной anti-DPI (лучшее на сегодня против flow-pattern detection ТСПУ).
2. **VLESS + Reality + XHTTP (H2)** — основной TCP (для сетей где UDP/QUIC шейпится).
3. **VLESS + Reality + XTLS-Vision** — legacy-совместимость для старых клиентов (v2rayNG <8.x и т.п.).
4. **Hysteria2** (UDP/443) — резерв для мобильных операторов, где TCP шейпится (Билайн/МТС).

Все inbound'ы отдаются в **одной subscription URL**. Современные клиенты (Hiddify ≥2.5, v2rayTun ≥2025.x, Karing, Streisand, Happ) сами выбирают лучший по latency/стабильности. Порядок приоритета в subscription: H3 → H2 → Vision → Hysteria2.

**Опционально:** AmneziaWG для самых заблокированных регионов.

### 2.3. Почему Reality + XHTTP
- **Reality** не имеет собственного TLS-сертификата — выполняет TLS-handshake к реальному «прикрытию» (`www.microsoft.com`), DPI видит HTTPS с этим доменом.
- **XHTTP** маскирует трафик внутри TLS-сессии под множество коротких HTTP/2 или HTTP/3 запросов — ломает flow-pattern detection ТСПУ (который в 2025 начал палить длинные TLS-сессии Reality+Vision по длительности/объёму).
- Комбинация = двойная маскировка: handshake + flow-pattern.
- **uTLS fingerprint** `chrome` — клиент неотличим от обычного Chrome.
- **Zero-copy** сохраняется на H2-stream'ах — скорость почти как у Vision.

---

## 3. Архитектура

```
┌──────────────────────────────────────────────────────────────┐
│              TELEGRAM BOT (aiogram 3, Python 3.12)           │
│   FSM-сценарии · Inline UI · Триал · Активация по коду       │
└──────────────────────┬───────────────────────────────────────┘
                       │ HTTPS (Cloudflare proxied)
                       ▼
┌──────────────────────────────────────────────────────────────┐
│        BACKEND API (FastAPI + PostgreSQL 16 + Redis 7)       │
│   Users · Codes · Subscriptions · Trials · Stats · Audit     │
└─────────┬────────────────────────────────────────┬───────────┘
          │ REST                                   │
          ▼                                        ▼
┌──────────────────────┐               ┌──────────────────────┐
│   PANEL: Remnawave   │               │ Notifications:       │
│   (форк Marzban)     │               │ Telegram push,       │
│                      │               │ Webhook bus          │
└──────────┬───────────┘               └──────────────────────┘
           │ gRPC / HTTP
           ▼
┌──────────────────────────────────────────────────────────────┐
│         FI-NODE — Helsinki (Ubuntu 24.04, Docker)            │
│   Xray-core (VLESS+Reality+Vision :443/TCP)                  │
│   Xray-core (Hysteria2 :443/UDP)                             │
│   AdGuard Home (DNS :53 localhost)                           │
│   Nginx (фасад-лендинг :80, маскировка)                      │
│   nftables · fail2ban · fwknop (SPA SSH) · cowrie honeypot   │
└──────────────────────────────────────────────────────────────┘
```

### 3.1. Стек технологий

| Слой | Технология | Обоснование |
|---|---|---|
| Бот | Python 3.12 + aiogram 3.x | Async, FSM, type-safe |
| Backend API | FastAPI + Pydantic v2 | Async, авто-доки OpenAPI |
| БД | PostgreSQL 16 + SQLAlchemy 2 (async) + asyncpg | JSONB + надёжность |
| Кэш / очереди | Redis 7 + arq (или dramatiq) | Триалы, rate-limit, фоновые задачи |
| VPN-панель | Remnawave (fallback: Marzban) | Современный API, multi-node, sub URL |
| VPN-ядро | Xray-core (latest stable) | Reality + XTLS-Vision |
| Резерв-протокол | Hysteria2 | UDP/443 |
| DNS-фильтр | AdGuard Home | Блок рекламы/трекеров/малвари |
| Reverse-proxy | Nginx + декоративный сайт | Маскировка |
| Контейнеризация | Docker + docker-compose | Воспроизводимость |
| CI/CD | GitHub Actions + Watchtower | Авто-обновление нод |
| Мониторинг | Prometheus + Grafana + Loki + Uptime-Kuma | Алерты |
| Mini-App / Admin | React 18 + Vite + TypeScript + TailwindCSS | + @telegram-apps/sdk-react |
| Secrets | sops + age (или Vault) | Никаких .env в репо |
| Infra | Terraform (hosting API) + Ansible (provisioning) | IaC |

---

## 4. Модель доступа (КЛЮЧЕВОЕ)

**Оплата происходит в личной переписке с админом.** Никаких встроенных платёжек в MVP. Бот — только система выдачи + управления.

### 4.1. Поток A — Триал (3 дня, бесплатно)
1. `/start` → приветственная карточка + 2 кнопки:
   - 🎁 **Попробовать 3 дня бесплатно**
   - 🔑 **У меня есть код**
2. Клик по триалу → анти-абуз чеки:
   - `tg_user_id` уникален (1 триал на аккаунт навсегда);
   - аккаунт старше 30 дней (по hint `user.id` / Premium-флагу), иначе бот просит «отправить контакт» (share phone), `fingerprint = sha256(phone + tg_id + salt)`;
   - fingerprint-хэш ранее не использовался;
   - rate-limit (Redis) по `tg_id`.
3. Выдача: подписка на 72 часа, 1 устройство, smart+adblock включены.
4. Напоминания за 24 ч / 6 ч / 1 ч до окончания + кнопка «💬 Написать админу для продления» (deep-link в ЛС).

### 4.2. Поток B — Активация по коду (основной после оплаты)
1. Пользователь пишет админу → оплачивает → получает код формата `XXXX-XXXX-XXXX`.
2. В боте жмёт 🔑 **У меня есть код** → вводит.
3. Бэкенд:
   - rate-limit: 5 попыток / 10 мин / `tg_user_id`, далее капча;
   - валидирует код (не USED / не EXPIRED / не REVOKED, в окне `valid_from..valid_until`);
   - проверяет `reserved_for_tg_id` (если задан) — должен совпадать;
   - привязывает к `tg_user_id`, активирует подписку с параметрами кода (см. §5.1);
   - переводит код в статус `ACTIVE`.
4. Код становится **single-use** и жёстко привязан к этому пользователю.

### 4.3. Поток C — Продление
- Пользователь получает новый код от админа → ⚙️ → **Применить код продления**.
- Если текущая подписка ещё активна → `expires_at += duration_days` (суммирование).
- Если истекла → `expires_at = now + duration_days` (замена).

### 4.4. Состояния кода
| Статус | Описание |
|---|---|
| `CREATED` | Создан в админке, не активирован |
| `ACTIVE` | Активирован, привязан к user_id, подписка работает |
| `EXPIRED` | Срок (`valid_until`) вышел до активации |
| `REVOKED` | Отозван админом (возврат, бан, мошенничество) |
| `USED_UP` | Использованы все лимиты (трафик/устройства) |

### 4.5. Инвариант
**1 активная subscription на user_id.** При новом коде — продление/замена, никогда не вторая подписка.

---

## 5. Админ-панель: управление кодами

### 5.1. Параметры кода (форма создания)

| Поле | Тип | Пример | Описание |
|---|---|---|---|
| `code` | string | `NEON-7F3K-P9QX` | Формат `XXXX-XXXX-XXXX`, читаемый алфавит (без `0/O`, `I/l`). Auto или ручной |
| `plan_name` | enum | `pro_1m`, `family_3m`, `lifetime` | Шаблон тарифа |
| `duration_days` | int | `30`, `90`, `365`, `0` (lifetime) | Срок подписки |
| `devices_limit` | int | `1–10` | Макс. одновременных устройств |
| `traffic_limit_gb` | int / null | `null` = безлимит | Квота трафика |
| `allowed_locations` | array | `[FI]`, `[FI,NL,DE]` | MVP: только FI |
| `adblock_default` | bool | `true` | По умолчанию вкл/выкл |
| `smart_routing_default` | bool | `true` | Умный режим по умолчанию |
| `valid_from` | datetime | `now` | С какой даты можно активировать |
| `valid_until` | datetime | `now+90д` | До какой даты можно активировать (НЕ срок подписки) |
| `single_use` | bool | `true` | Привязка к одному `tg_user_id` |
| `reserved_for_tg_id` | bigint / null | `null` | Резерв под конкретного юзера |
| `note` | text | «оплата Иван 500р 19.04» | Внутренний комментарий |
| `tag` | string | `manual`, `promo`, `refund` | Для фильтрации |
| `price_rub` | decimal | `490.00` | Сумма (для учёта выручки) |
| `payment_method` | enum | `card`, `usdt`, `crypto_other`, `sbp`, `stars`, `gift` | Для статистики |

### 5.2. Действия над кодом
- **View** — карточка с историей: создан → активирован (user X, дата) → продления → отзыв.
- **Revoke** — мгновенный отзыв (юзер получает уведомление + отключение в Remnawave).
- **Edit** — менять параметры до активации; после — только `devices_limit`, `traffic_limit_gb`, upgrade `plan_name`.
- **Regenerate** — пересоздать код, старый инвалидировать (если потерян).
- **Clone** — создать такой же для повторной продажи.
- **Extend** — добавить N дней к уже активированной подписке.
- **Batch generate** — CSV/JSON: 50 кодов `pro_1m` одной командой, экспорт в TXT/CSV.
- **QR** — сгенерировать QR-код для печати/пересылки.

### 5.3. Главный экран — таблица кодов
**Колонки:** `Code | Plan | Duration | Devices | Status | User (tg) | Created | Activated | Expires | Price | Method | Tag | Actions`

**Фильтры:** статус, дата (created/activated/expires), план, метод оплаты, тег, поиск по коду / tg-юзеру.

### 5.4. Сводные виджеты
- **Выручка** (день/неделя/месяц) — сумма `price_rub` по активированным.
- **Конверсия:** `активированных / созданных × 100%`.
- Средний чек, средний срок.
- Топ-теги (промо, возвраты).
- **«Висящие» коды** — созданы >N дней и не активированы.
- **Истекают в ближайшие 3/7 дней** — для upsell-рассылки.

### 5.5. Anti-abuse
- Лог всех попыток ввода неверных кодов (`code_attempts`).
- Rate-limit: 5 попыток / 10 мин / `tg_user_id`, далее капча.
- Блек-лист `tg_user_id`.
- Алерт админу при >10 неуспехах с одного IP/tg за час.

### 5.6. Дополнительные «умные» фичи админки
- **AI-аналитика churn** — еженедельный отчёт «кто скоро отвалится» по паттернам трафика.
- **Auto-promo:** триал заканчивается через 6 ч → авто-предложение скидки 30%.
- **Heat-map нагрузки** по странам/нодам/часам.
- **Speed-leaderboard нод** — какая нода даёт лучший Mbps.
- **Auto-A/B** для текстов офферов в боте.
- **Anti-fraud сканер**: подозрительные паттерны (10 триалов с одного IP, ключи на 1 человека продаются другим).
- **One-click backup**: всё состояние БД + конфиги в encrypted-архив на S3.
- **Cost-tracker**: автоматическая раскладка расходов по нодам vs выручка.
- **«Кнопка SOS»** — массовая ротация всех IP + рассылка инструкций.
- **Webhook-bus** — события (новый платёж, бан, ротация) шлются в Discord/Slack/Telegram-канал команды.

### 5.7. Стек админки
- **Frontend:** React 18 + Vite + TypeScript + TailwindCSS + Mantine UI (или shadcn/ui).
- **Auth:** OAuth2 + TOTP (Google Authenticator) + IP-allowlist + Telegram-подтверждение критичных действий.
- **Доступ:** только через VPN/whitelist, отдельный поддомен, не индексируется.
- **Дизайн:** строго `Design.txt` — bg `#121212`, surface `#181818`, акцент `#1ed760`, pill-buttons.

---

## 6. Бот — UX и контент (для пользователя)

### 6.1. Главное меню (после активации)
```
🎵 Мой VPN
   ├─ 🔗 Моя подписка
   ├─ 📱 Подключить устройство
   ├─ 📊 Статистика
   └─ 🇫🇮 Локация: Helsinki

📡 Telegram-прокси (MTProto)
   └─ ⚡ Подключить в один клик

🔑 Активировать / продлить код

⚙️ Настройки
   ├─ 🇷🇺 Умный режим (вкл)
   ├─ 🛡 Блок рекламы (вкл)
   └─ 🔔 Уведомления

❓ Помощь
   ├─ Инструкции по платформам
   ├─ FAQ
   └─ 💬 Связаться с админом
```

### 6.2. Визуальные принципы (Spotify-dark по `Design.txt`)
- Каждое сообщение — карточка с эмодзи-заголовком, разделителями `━━━━`, чёткой иерархией.
- Главные действия — крупные inline-кнопки в 1–2 ряда, **UPPERCASE** ярлыки имитируют pill Spotify (`ПОДКЛЮЧИТЬ`, `СКОПИРОВАТЬ`, `QR`).
- Markdown V2 + HTML-форматирование + видео-стикеры приветствия.
- Брендированные эмодзи (Telegram Premium emoji при наличии).
- Длинные списки — пагинация.
- При генерации ключа — анимация `typing…` + загрузочная карточка.
- Карточки-картинки рендерятся через Pillow: фон `#121212`, заголовок белым `Inter/Manrope` (свободный аналог CircularSp), акцент `#1ed760`.

### 6.3. Пример карточки активации
```
🎧 VPN АКТИВИРОВАН
━━━━━━━━━━━━━━━━━━━━━━━━
🔑 План:        PRO · 30 дней
📅 Действует до: 19.05.2026
🇫🇮 Сервер:      Helsinki
📱 Устройств:    до 3
🛡 Реклама:      блокируется
🇷🇺 Smart:       вкл
━━━━━━━━━━━━━━━━━━━━━━━━
Выбери систему:
[ IOS ]   [ ANDROID ]   [ WINDOWS ]
[ MACOS ] [ LINUX ]     [ ТВ / РОУТЕР ]

[ 🔗 КОПИРОВАТЬ ССЫЛКУ ]  [ 📷 QR ]
```

### 6.4. Дополнительные «вкусные» фичи
- **Speed-test из бота** — кнопка запускает тест с ноды, возвращает Mbps вверх/вниз.
- **Health-check** — каждые 6 ч проверяет ключ юзера; если нода легла → авто-миграция + уведомление.
- **«Пинг до сервиса»** — пользователь вводит домен, бот возвращает RTT (помогает геймерам).
- **Мульти-устройства** — на 1 подписку до N конфигов, управление списком + «отозвать».
- **Тёмный режим бота** — сезонные темы (Новый Год и т.д.).
- **Геймификация** — ачивки за рефералы, за месяц, за speed-test.
- **Бренд-стикеры** — собственный sticker-pack с маскотом (лиса/енот «обходящий стену»).

---

## 7. Telegram Mini-App (WebApp)

Полноценный визуальный интерфейс — в Mini-App (кнопка 🎵 Мой VPN → **Открыть приложение**). Это главный канал UX, т.к. в обычном чате Telegram нельзя менять шрифты/цвета.

### 7.1. Стек
- React 18 + Vite + TypeScript.
- `@telegram-apps/sdk-react` (WebApp init, HapticFeedback, MainButton, BackButton).
- TailwindCSS с CSS-переменными из `Design.txt`.
- Recharts — графики трафика.
- `qrcode.react` — QR.

### 7.2. Экраны
- **Home** — карточка подписки как Spotify «Now Playing»: fullscreen pill-card `#181818`, центральный зелёный play-button «Подключено ✓», счётчики «дней осталось», «устройств», «трафик».
- **Devices** — список устройств как плейлист: строка = устройство, pill-кнопка `ОТОЗВАТЬ`.
- **Instructions** — grid 2×3 «обложек» платформ (как album-grid Spotify); клик → full-screen инструкция со скриншотами + deep-link.
- **Stats** — график трафика (area-chart, зелёный градиент), метрики день/неделя/месяц.
- **Settings** — Spotify-style toggles (тёмно-серый трек, зелёный thumb): Smart mode, AdBlock, уведомления.
- **Contact** — кнопка deep-link в ЛС админа.

### 7.3. Tailwind config (ключевые токены из `Design.txt`)
```js
theme: {
  extend: {
    colors: {
      bg:          '#121212',
      surface:     '#181818',
      surface2:    '#1f1f1f',
      card:        '#252525',
      card2:       '#272727',
      text:        '#ffffff',
      muted:       '#b3b3b3',
      border:      '#4d4d4d',
      lightBorder: '#7c7c7c',
      accent:      '#1ed760',
      accentAlt:   '#1db954',
      error:       '#f3727f',
      warning:     '#ffa42b',
      info:        '#539df5',
    },
    fontFamily: {
      ui:    ['SpotifyMixUI','Inter','Manrope','Helvetica Neue','Arial','sans-serif'],
      title: ['SpotifyMixUITitle','Inter','Manrope','Helvetica Neue','Arial','sans-serif'],
    },
    borderRadius: { pill: '500px', full: '9999px', card: '8px' },
    boxShadow: {
      dialog: 'rgba(0,0,0,0.5) 0px 8px 24px',
      card:   'rgba(0,0,0,0.3) 0px 8px 8px',
      inset:  'rgb(18,18,18) 0px 1px 0px, rgb(124,124,124) 0px 0px 0px 1px inset',
    },
    letterSpacing: { btn: '1.6px' },
  }
}
```

### 7.4. Базовые компоненты
- **Кнопка (dark pill):** `bg-surface2 text-text rounded-full px-4 py-2 text-[14px] font-bold uppercase tracking-btn`.
- **Primary/play:** `bg-accent text-black rounded-full` (circular для play — `rounded-[50%]`).
- **Cards:** `bg-surface rounded-card shadow-card p-6`.

---

## 8. Smart-routing (split-tunneling) для РФ

### 8.1. Принцип
Subscription отдаёт routing-rules JSON (singbox / mihomo / clash YAML в зависимости от клиента), который понимают Hiddify, v2rayTun, Karing, Happ, NekoBox:

```
direct  ⇐ geosite:category-ru, geoip:ru, custom RU-list
proxy   ⇐ всё остальное
block   ⇐ geosite:category-ads-all + custom adblock
```

### 8.2. Источники RU-списков (auto-update каждые 6 ч)
- `github.com/runetfreedom/russia-blocked-geoip`
- `community.antifilter.download`
- `github.com/v2fly/domain-list-community` (`geosite:category-ru`)
- `github.com/Loyalsoldier/v2ray-rules-dat` (`geoip.dat` / `geosite.dat`)
- Кастомный YAML в репо, редактируется через админку.

### 8.3. Кастомный RU-список (категории)
- **Банки:** `*.sber*`, `*.tbank.ru`, `*.tinkoff.ru`, `vtb.ru`, `alfabank.ru`, `raiffeisen.ru`, `gazprombank.ru`.
- **Госуслуги:** `gosuslugi.ru`, `nalog.gov.ru`, `pfr.gov.ru`, `mvd.ru`, `gibdd.ru`, `mos.ru`, `pochta.ru`, `*.gov.ru`.
- **Yandex:** `*.yandex.*` (поиск, карты, такси, еда, маркет, музыка, диск, плюс), `ya.ru`, `kinopoisk.ru`.
- **VK Group:** `vk.com`, `vk.ru`, `vkvideo.ru`, `ok.ru`, `mail.ru`, `*.dzen.ru`.
- **Маркетплейсы:** `wildberries.ru`, `ozon.ru`, `avito.ru`, `market.yandex.ru`, `megamarket.ru`, `lamoda.ru`.
- **Стриминг:** `wink.ru`, `okko.tv`, `premier.one`, `ivi.ru`, `start.ru`, `more.tv`, `kion.ru`, `rutube.ru`.
- **Доставка:** `eda.yandex`, `delivery-club.ru`, `samokat.ru`, `vkusvill.ru`, `perekrestok.ru`, `lavka.yandex`.
- **Связь:** `mts.ru`, `beeline.ru`, `megafon.ru`, `tele2.ru`, `yota.ru`, `t2.ru`.
- **СБП/API банков:** `cbr.ru`, `nspk.ru`.
- **Прочее:** `2gis.ru`, `hh.ru`, `sravni.ru`, `cian.ru`, `domclick.ru`, `auto.ru`, `drom.ru`.

### 8.4. Subscription URL
Формат:
```
https://sub.example.com/<sub_url_token>?routing=smart&adblock=on
```
Параметры `routing` (`smart`/`off`) и `adblock` (`on`/`off`) меняются через бот/Mini-App (настройки).

---

## 9. Блокировка рекламы

### 9.1. Уровень DNS (AdGuard Home на ноде)
- Слушает `127.0.0.1:53`, Xray направляет DNS-запросы клиентов через `dns: { servers: ["127.0.0.1"] }`.
- Подписки AGH:
  - AdGuard Base + AdGuard Mobile
  - EasyList + EasyPrivacy
  - OISD Big (anti-malware + anti-ads)
  - HaGeZi Pro (агрессивный)
  - RU AdList (Adguard Russian)
  - NoCoin (анти-майнинг в браузере)
  - Фильтр телеметрии Windows/Apple/Google (опц., по флагу)

### 9.2. Уровень routing внутри клиента
Дополнительно в правилах `geosite:category-ads-all → block` — отрезает рекламу до DNS.

### 9.3. Toggle пользователя
Через бота/Mini-App пользователь включает/выключает → отдаётся другая subscription URL с `?adblock=off`.

---

## 9A. MTProto-прокси для Telegram (отдельный сервис)

В дополнение к VPN, бот выдаёт **MTProto-прокси** для самого мессенджера Telegram. Зачем: если в РФ начнут жёстко блокировать сам Telegram (как было в 2018–2020 и периодически грозит сейчас), пользователь сможет подключаться к Telegram через прокси одним нажатием — VPN при этом не нужен.

### 9A.1. Зачем отдельно от VPN
- **Не требует VPN-клиента** — прокси конфигурится прямо в Telegram (Settings → Data → Proxy), работает на всех платформах нативно.
- **Минимальный оверхед** — Telegram через MTProto работает быстрее, чем через VPN-туннель.
- **Точка входа в бота** — даже если у юзера VPN отвалился, он сможет открыть бота через прокси и получить новые конфиги.
- **Sponsored channel** — MTProto-прокси умеет показывать «спонсируемый канал» в списке у юзеров, можно использовать для маркетинга своего же канала.

### 9A.2. Стек
- **mtg** (`9seconds/mtg`) — современный Go-implementation MTProto-прокси с Fake-TLS (имитирует TLS-handshake к произвольному `cloak`-домену типа `www.google.com`).
- **Деплой:** отдельный Docker-контейнер на той же FI-ноде (или отдельная микро-нода 1 vCPU / 1 GB).
- **Порт:** `:8443/tcp` (или `:443/tcp` если основной VPN на UDP-only). При коллизии — отдельный IPv4 на хосте, mtg на :443.
- **Fake-TLS cloak:** `www.google.com`, `www.cloudflare.com`, `www.microsoft.com`.

### 9A.3. Конфигурация mtg

```toml
# /etc/mtg/config.toml
secret      = "<EE-prefix hex secret, generated per user OR shared>"
bind-to     = "0.0.0.0:8443"
concurrency = 8192

[network]
prefer-ip = "prefer-ipv4"

[stats]
prometheus = "127.0.0.1:9410"

[defense.anti-replay]
enabled        = true
max-size       = "1mb"
error-rate     = 0.001

[defense.allow-list]
# опционально, можно ограничить странами/ASN
```

### 9A.4. Модель выдачи MTProto-секретов
Два режима, выбираются админом per-code:

**A. Shared secret (по умолчанию)** — один секрет на всю ноду, выдаётся всем активным юзерам. Простой, экономичный, но при компрометации меняется для всех.

**B. Per-user secret** — каждому юзеру выдаётся свой секрет (mtg поддерживает множественные через replicas или несколько процессов на разных портах). Сложнее в управлении, но позволяет ревокать индивидуально и считать трафик per-user.

**MVP: режим A (shared) + ротация секрета раз в 30 дней + при подозрении на утечку.**

### 9A.5. UX в боте
Раздел **«📡 Telegram-прокси»** в главном меню:
```
📡 TELEGRAM ПРОКСИ
━━━━━━━━━━━━━━━━━━━━━━━━
Если Telegram заблокирован
или работает медленно — нажми
кнопку ниже, и приложение
само настроит прокси.

🇫🇮 Сервер: Helsinki
🛡 Тип:     MTProto + Fake-TLS

[ ⚡ ПОДКЛЮЧИТЬ В ОДИН КЛИК ]
[ 📷 QR-код ]
[ 📋 Скопировать ссылку ]
[ ❓ Что это? ]
```

**Deep-link для Telegram (one-click):**
```
tg://proxy?server=fi-01.example.com&port=8443&secret=ee...
https://t.me/proxy?server=fi-01.example.com&port=8443&secret=ee...
```
Кнопка `⚡ ПОДКЛЮЧИТЬ В ОДИН КЛИК` — это `t.me/proxy?...` URL inline-кнопкой. Telegram сам открывает диалог «Подключить прокси?».

### 9A.6. Доступность
- MTProto-прокси доступен **всем** пользователям с активной подпиской (включая триал) — без дополнительных кодов.
- Опционально: **публичный free-tier MTProto** (без подписки, ограничение по rate-limit) как лид-магнит для канала. Управляется флагом в админке (`MTPROTO_PUBLIC_ENABLED`).

### 9A.7. Админка
Раздел **«MTProto»**:
- Текущий секрет (shared) + кнопка `Rotate` (с подтверждением + автоматическая рассылка нового deep-link всем активным юзерам).
- Метрики: подключения / Mbps / уникальные IP-хэши.
- Sponsored channel ID (поле для канала-«паразита»).
- Список cloak-доменов с возможностью ротации.
- Toggle public free-tier.

### 9A.8. Защита и стелс
- mtg за nftables, разрешён только tcp/8443.
- Fake-TLS cloak обновлять раз в неделю (cron).
- Anti-replay включён (см. конфиг).
- IP-блок сканеров (тот же scanner-set из nftables §11.1).
- Логи без PII (как и весь стек).

### 9A.9. БД (расширение)
```sql
mtproto_secrets (
  id              uuid PRIMARY KEY,
  secret_hex      text UNIQUE NOT NULL,            -- EE-prefixed hex
  cloak_domain    text NOT NULL,
  scope           text NOT NULL,                   -- 'shared' | 'user'
  user_id         bigint REFERENCES users(tg_id),  -- NULL для shared
  status          text NOT NULL,                   -- ACTIVE/ROTATED/REVOKED
  created_at      timestamptz NOT NULL DEFAULT now(),
  rotated_at      timestamptz,
  last_used_at    timestamptz
);
```

---


## 10. Инфраструктура — Финская нода

### 10.1. Сервер
- **Локация:** Helsinki (FI).
- **Рекомендуемые провайдеры:** Aeza FI, PQ.Hosting FI, Stark Industries FI, UpCloud FI. Hetzner FI допустим для MVP, но часто палится — закладываем гибкую ротацию.
- **Спецификация MVP-ноды:** 4 vCPU / 8 GB RAM / 80 GB NVMe / 1 Gbps unmetered / IPv4 + IPv6 / Ubuntu 24.04 LTS.
- **Резервные IP:** 2 дополнительных IPv4 у того же провайдера для быстрой ротации.
- **DNS:** Cloudflare (proxied для API/подписки, non-proxied для VPN inbound).

### 10.2. Стек на ноде (docker-compose)
- `xray-core` — VLESS+Reality+Vision (inbound `:443/TCP`) + Hysteria2 (inbound `:443/UDP`).
- `adguardhome` — DNS на `127.0.0.1:53`.
- `nginx` — фасад-лендинг на `:80` (редирект `:443` → реальный статический сайт «Finnish Cloud Services»).
- `remnawave-node-agent` — gRPC к control-plane.
- `fail2ban` + `nftables`.
- `fwknop` — SPA (single-packet authorization) для SSH.
- `cowrie` — honeypot на `:22`.
- `promtail` → Loki (на control-plane).
- `node_exporter` → Prometheus.

### 10.3. Xray baseline config (Reality + XHTTP H3/H2 + Vision + Hysteria2)

```json
{
  "log": { "loglevel": "warning" },
  "inbounds": [
    {
      "tag": "vless-reality-xhttp-h3",
      "listen": "0.0.0.0",
      "port": 443,
      "protocol": "vless",
      "settings": {
        "clients": [],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "xhttp",
        "security": "reality",
        "xhttpSettings": {
          "host": "www.microsoft.com",
          "path": "/api/v1/feed",
          "mode": "stream-one",
          "extra": { "scMaxEachPostBytes": 1000000, "scMaxConcurrentPosts": 100 }
        },
        "realitySettings": {
          "show": false,
          "dest": "www.microsoft.com:443",
          "xver": 0,
          "serverNames": ["www.microsoft.com"],
          "privateKey": "<GENERATED>",
          "minClientVer": "25.1.0",
          "shortIds": ["", "<random_8hex>"]
        }
      },
      "sniffing": { "enabled": true, "destOverride": ["http","tls","quic"] }
    },
    {
      "tag": "vless-reality-xhttp-h2",
      "listen": "0.0.0.0",
      "port": 443,
      "protocol": "vless",
      "settings": { "clients": [], "decryption": "none" },
      "streamSettings": {
        "network": "xhttp",
        "security": "reality",
        "xhttpSettings": {
          "host": "www.microsoft.com",
          "path": "/api/v2/sync",
          "mode": "packet-up"
        },
        "realitySettings": {
          "show": false,
          "dest": "www.microsoft.com:443",
          "xver": 0,
          "serverNames": ["www.microsoft.com"],
          "privateKey": "<GENERATED>",
          "shortIds": ["", "<random_8hex>"]
        }
      },
      "sniffing": { "enabled": true, "destOverride": ["http","tls"] }
    },
    {
      "tag": "vless-reality-vision",
      "listen": "0.0.0.0",
      "port": 8443,
      "protocol": "vless",
      "settings": { "clients": [], "decryption": "none" },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "www.microsoft.com:443",
          "xver": 0,
          "serverNames": ["www.microsoft.com"],
          "privateKey": "<GENERATED>",
          "minClientVer": "1.8.0",
          "shortIds": ["", "<random_8hex>"]
        }
      },
      "sniffing": { "enabled": true, "destOverride": ["http","tls","quic"] }
    },
    {
      "tag": "hysteria2",
      "listen": "0.0.0.0",
      "port": 8444,
      "protocol": "hysteria2",
      "settings": {
        "password": "<GENERATED>",
        "obfs": { "type": "salamander", "password": "<GENERATED>" }
      },
      "streamSettings": { "network": "udp" }
    }
  ],
  "outbounds": [
    { "tag": "direct", "protocol": "freedom", "settings": { "domainStrategy": "UseIPv4v6" } },
    { "tag": "block",  "protocol": "blackhole" }
  ],
  "dns": { "servers": ["127.0.0.1"] },
  "routing": {
    "domainStrategy": "IPIfNonMatch",
    "rules": [
      { "type": "field", "domain": ["geosite:category-ads-all"], "outboundTag": "block" },
      { "type": "field", "ip": ["geoip:private"], "outboundTag": "block" }
    ]
  }
}
```

**Примечания:**
- XHTTP H3 и H2 inbound'ы оба слушают `:443` (H3 на UDP, H2 на TCP) — мультиплексирование на одном порту через разные пути (`/api/v1/feed`, `/api/v2/sync`).
- Vision inbound — на `:8443/tcp` для legacy-клиентов; в subscription URL отдаётся как fallback.
- Hysteria2 — на `:8444/udp` (отдельный порт от XHTTP H3 чтобы не конфликтовать).
- `mode: "stream-one"` для H3 — рекомендуется для anti-DPI (один длинный POST).
- `mode: "packet-up"` для H2 — стандартный режим.

### 10.4. Рекомендуемые Reality-прикрытия (2025–2026)
- `www.microsoft.com`
- `dl.google.com`
- `www.apple.com`
- `cdn.discordapp.com`
- `www.cloudflare.com`

**Требования:** TLS 1.3 + HTTP/2, без ESNI, стабильный IP, не заблокирован в РФ.

---

## 11. Защита и стелс

### 11.1. Сетевой периметр
- **Открытые порты:** только `:80/tcp` (Nginx-лендинг), `:443/tcp` (Reality), `:443/udp` (Hysteria2). Всё остальное — `DROP`.
- **SSH:** порт `:62222`, key-only, доступен **только после fwknop SPA**. На `:22` — Cowrie honeypot.
- **nftables baseline:**
  ```
  table inet filter {
    set scanners4 { type ipv4_addr; flags interval; elements = { ... Censys/Shodan/GreyNoise/BinaryEdge AS ... } }
    chain input {
      type filter hook input priority 0; policy drop;
      ct state established,related accept
      iif lo accept
      ip saddr @scanners4 drop
      tcp dport { 80, 443 } accept
      udp dport 443 accept
    }
  }
  ```

### 11.2. Маскировка
- **Nginx-лендинг:** статический сайт «Finnish Cloud Services» (нейтральная тематика — хостинг/IT-услуги), ни намёка на VPN.
- **Reality-инбаунд** работает поверх того же `:443` через `dest` (фоллбэк на легитимный сайт).
- **Remnawave-панель** слушает только `127.0.0.1`, наружу — через WireGuard-tunnel в админскую сеть.
- **Скрытие от сканеров:** блокировать AS Censys/Shodan/GreyNoise/BinaryEdge в nftables, отдавать им `RST`.

### 11.3. Сеть / производительность
- **BBR v3** включён (`net.ipv4.tcp_congestion_control=bbr`, `net.core.default_qdisc=fq`).
- **MTU 1420** для WG/Hysteria.
- **TLS uTLS fingerprint** клиента — `chrome`.

### 11.4. Авто-ротация IP (антиблок)
- Воркер **«Probe RU»** на control-plane: с 3–5 резидентных RU-прокси каждые 10 мин проверяет FI-ноду.
- Если 3 фейла подряд из РФ, но доступно из ЕС → нода помечается `BURNED`:
  1. Стоп выдачи новых подписок на неё.
  2. API хостера меняет IP на запасной (Aeza/PQ умеют).
  3. После ротации → `HEALTHY`.
  4. Уведомление админу + всем активным юзерам: «Сервер обновлён, переподключение автоматическое».

### 11.5. Дополнительные защитные меры
- **CDN-fronting** для control-plane: API бэкенда и subscription URL за Cloudflare.
- **Domain rotation:** subscription URL через `*.workers.dev` или свой домен с возможностью миграции (DoH у клиента).
- **2FA admin:** TOTP + IP whitelist + Telegram-подтверждение каждого критичного действия.
- **E2E-шифрование ключей в БД:** UUID/коды хранятся в libsodium secretbox, ключ из KMS/sops, расшифровка только в момент выдачи.
- **Логирование без PII:** IP подключений — только sha256, без сырых.
- **Auto-scaling по нагрузке:** Terraform-модуль для разворачивания новой ноды одним кликом.
- **WARP-fallback:** если все ноды лежат → временный WARP-конфиг как Plan-Z.

### 11.6. Бэкапы и восстановление
- **Borg → S3-совместимое** (iDrive e2 / Backblaze B2), ежечасно.
- Ежедневные снапшоты, 7-дневный rolling + еженедельные 30-дневные.
- Тест восстановления раз в месяц (runbook в `docs/RUNBOOK.md`).

---

## 11A. Доменная архитектура

У проекта **есть собственный домен** (далее — `example.com`, подставить реальный). Домен — ключевой актив для легитимного вида, anti-block устойчивости и брендинга.

### 11A.1. Структура поддоменов

| Поддомен | Назначение | Cloudflare | SSL |
|---|---|---|---|
| `example.com` | Лендинг-фасад «Finnish Cloud Services» (нейтральный, без упоминания VPN) | ✅ Proxied | Cloudflare Universal |
| `www.example.com` | 301 → `example.com` | ✅ Proxied | — |
| `api.example.com` | Backend FastAPI (бот + Mini-App вызывают) | ✅ Proxied | Full (strict) |
| `sub.example.com` | Выдача subscription URL (`/<token>`) | ✅ Proxied (через Worker) | Full (strict) |
| `app.example.com` | Telegram Mini-App (Cloudflare Pages) | ✅ Proxied | Cloudflare |
| `admin.example.com` | Админ-панель (Cloudflare Pages + Access) | ✅ Proxied + Zero Trust | Cloudflare |
| `status.example.com` | Публичный Uptime-Kuma | ✅ Proxied | Cloudflare |
| `dns.example.com` | DoH endpoint (Cloudflare Worker) | ✅ Proxied | Cloudflare |
| `fi-01.example.com` | A → IP FI-ноды (VPN inbound, **non-proxied**) | ❌ DNS-only | Let's Encrypt на ноде |
| `fi-02.example.com` | Резервная нода (non-proxied) | ❌ DNS-only | LE |
| `mtp.example.com` | MTProto-прокси (non-proxied, раздельный IP если возможно) | ❌ DNS-only | — (Fake-TLS) |
| `n.example.com` | Короткие редиректы (QR, sticker pack, deep-links) | ✅ Proxied | Cloudflare |

**Ключевой принцип:** control-plane (HTTP) — всё за Cloudflare proxied. Data-plane (VPN/MTProto) — non-proxied A-records (CF не умеет TCP/UDP tunneling на free-плане).

### 11A.2. Cloudflare настройки (free-plan хватит)

**DNS & SSL:**
- Перенести NS регистратора на Cloudflare.
- SSL/TLS: **Full (strict)** — ноды держат валидные Let's Encrypt (Caddy автосерт).
- **Always Use HTTPS** + **HSTS** (`max-age=31536000; includeSubDomains; preload`).
- **DNSSEC** включён.
- **CAA запись:** `example.com. CAA 0 issue "letsencrypt.org"` + `CAA 0 issuewild ";"`.

**Security:**
- **Bot Fight Mode** на `api.`, `admin.`, `sub.`.
- **WAF custom rules** для `admin.`: allow только IP-allowlist + geo=RU (если админ в РФ) → иначе challenge.
- **Firewall rules** на `api.`: rate-limit 100 req/min/IP для `/activate` и `/trial`.
- **Page Rules / Cache Rules:** `api.*` и `sub.*` — `Cache Level: Bypass`.
- **Zero Trust Access** на `admin.example.com` — бесплатно до 50 юзеров, даёт email-OTP / Google / GitHub SSO + device posture + IP-allowlist. **Это заменяет собственный TOTP в MVP.**

**Performance:**
- **Tiered Cache** на `app.` и `example.com` (статика).
- **Cloudflare Workers** для `sub.` — edge-endpoint для subscription JSON (кеш + защита + низкая задержка из РФ).

### 11A.3. Email на домене
- `admin@example.com`, `support@example.com`, `abuse@example.com`.
- **Cloudflare Email Routing** (бесплатно) → forward на личный Gmail.
- **SPF:** `"v=spf1 -all"` (если не шлём — жёсткий deny).
- **DKIM:** настроить если будем слать (Resend / Postmark / Zoho Free).
- **DMARC:** `"v=DMARC1; p=reject; rua=mailto:abuse@example.com"`.
- **MTA-STS + TLS-RPT** — плюс к доверию.

### 11A.4. Reality dest и домен
**ВАЖНО:** собственный домен **НЕ использовать** как `dest`/`serverNames` для Reality. Reality нужен чужой «жирный» сайт-прикрытие (`www.microsoft.com`). Свой домен в роли dest = минус маскировка.

Собственный домен полезен иначе:
- **Nginx-фасад на ноде** (`fi-01.example.com`) — валидный TLS-серт, статический лендинг «Finnish Cloud Services». Даёт легитимность ноде при визите сканера или curl.
- **Subscription URL** — `https://sub.example.com/<token>` выглядит официально (vs. `*.workers.dev`).
- **Admin / WebApp URLs** — чистый бренд в Telegram Mini-App settings.

### 11A.5. Anti-block фичи домена

- **Multi-domain fallback:** купить 2-й домен (на другом регистраторе + другом TLD, напр. `.xyz`, `.io`). В Mini-App и боте список «резервных API endpoints». При `api.example.com` недоступен → фоллбэк на `api.example.io`.
- **DoH собственный:** `https://dns.example.com/dns-query` через Cloudflare Worker. Обход DNS-блокировок у провайдеров РФ. Клиент Mini-App использует именно его.
- **Domain warming:** купить домен заранее, минимум 30 дней до релиза гонять на нём невинный трафик (лендинг с SEO). «Свежие» домены блокируются и фильтруются быстрее.
- **CNAME flattening** для apex — Cloudflare умеет из коробки.
- **Subresource Integrity (SRI)** для JS на Mini-App — защита от подмены на уровне CDN.

### 11A.6. robots & privacy
- `robots.txt` на `app.`, `admin.`, `sub.` — `Disallow: /` + `X-Robots-Tag: noindex, nofollow`.
- `app.example.com/privacy` — краткая privacy-policy (обязательна для Telegram Mini-App в сторах).
- `app.example.com/terms` — условия использования.
- Нигде на публичных страницах слов «VPN», «обход», «Роскомнадзор». Только нейтральное «cloud networking», «secure tunnelling», «IT infrastructure services».

### 11A.7. Инфра-as-Code (Terraform)
Модуль `infra/cloudflare.tf`:
```hcl
resource "cloudflare_record" "api"  { zone_id = var.zone; name = "api";   type = "A"; value = var.cf_edge; proxied = true  }
resource "cloudflare_record" "sub"  { zone_id = var.zone; name = "sub";   type = "A"; value = var.cf_edge; proxied = true  }
resource "cloudflare_record" "fi01" { zone_id = var.zone; name = "fi-01"; type = "A"; value = var.fi01_ip; proxied = false }
resource "cloudflare_record" "mtp"  { zone_id = var.zone; name = "mtp";   type = "A"; value = var.mtp_ip;  proxied = false }
# + Access policies, WAF rules, Pages projects, Workers — всё в коде
```

### 11A.8. OG-preview для Telegram
Когда пользователь шлёт ссылку на бота — в чате показывается красивая карточка:
- `og:image` — 1200×630, брендированный (чёрный фон #121212, логотип, slogan).
- `og:title` = `Vlessich — Private Network`
- `og:description` = нейтральный текст без VPN.

Хостим на `example.com/og/*.png` через Cloudflare Pages + `_headers` файл (`Cache-Control: public, max-age=31536000, immutable`).

---


## 12. База данных (схема)

```sql
-- КОДЫ (главная сущность)
codes (
  id                    uuid PRIMARY KEY,
  code                  text UNIQUE NOT NULL,       -- XXXX-XXXX-XXXX
  plan_name             text NOT NULL,
  duration_days         int NOT NULL,               -- 0 = lifetime
  devices_limit         int NOT NULL,
  traffic_limit_gb      int,
  allowed_locations     text[] NOT NULL,
  adblock_default       bool NOT NULL DEFAULT true,
  smart_routing_default bool NOT NULL DEFAULT true,
  valid_from            timestamptz NOT NULL,
  valid_until           timestamptz NOT NULL,
  single_use            bool NOT NULL DEFAULT true,
  reserved_for_tg_id    bigint,
  status                text NOT NULL,              -- CREATED/ACTIVE/EXPIRED/REVOKED/USED_UP
  note                  text,
  tag                   text,
  price_rub             numeric(10,2),
  payment_method        text,                       -- card/usdt/sbp/stars/gift/...
  created_by_admin      int REFERENCES admins(id),
  created_at            timestamptz NOT NULL DEFAULT now(),
  activated_by_user     bigint REFERENCES users(tg_id),
  activated_at          timestamptz,
  revoked_at            timestamptz,
  revoke_reason         text
);

-- ПОДПИСКИ (создаются при активации кода)
subscriptions (
  id                uuid PRIMARY KEY,
  user_id           bigint NOT NULL REFERENCES users(tg_id),
  code_id           uuid REFERENCES codes(id),
  started_at        timestamptz NOT NULL,
  expires_at        timestamptz,                    -- NULL для lifetime
  devices_limit     int NOT NULL,
  traffic_limit_gb  int,
  traffic_used_gb   numeric NOT NULL DEFAULT 0,
  adblock           bool NOT NULL,
  smart_routing     bool NOT NULL,
  status            text NOT NULL,                  -- ACTIVE/EXPIRED/SUSPENDED
  sub_url_token     text UNIQUE NOT NULL
);

-- USERS
users (
  tg_id            bigint PRIMARY KEY,
  tg_username      text,
  lang             text DEFAULT 'ru',
  created_at       timestamptz NOT NULL DEFAULT now(),
  banned           bool NOT NULL DEFAULT false,
  fingerprint_hash text,                            -- sha256(phone+tg_id+salt)
  referrer_id      bigint REFERENCES users(tg_id)
);

-- TRIALS (1 на пользователя навсегда)
trials (
  user_id          bigint PRIMARY KEY REFERENCES users(tg_id),
  started_at       timestamptz NOT NULL,
  expires_at       timestamptz NOT NULL,
  fingerprint_hash text NOT NULL
);

-- DEVICES
devices (
  id              uuid PRIMARY KEY,
  subscription_id uuid NOT NULL REFERENCES subscriptions(id),
  name            text,
  xray_uuid_enc   bytea NOT NULL,                   -- libsodium secretbox
  created_at      timestamptz NOT NULL DEFAULT now(),
  last_seen       timestamptz,
  ip_hash         text                              -- sha256, no raw IP
);

-- NODES (MVP: 1 шт. в FI)
nodes (
  id              serial PRIMARY KEY,
  name            text NOT NULL,                    -- FI-Helsinki-01
  country         text NOT NULL,
  host            text NOT NULL,
  ip_public       inet NOT NULL,
  ip_admin        inet NOT NULL,                    -- management
  status          text NOT NULL,                    -- HEALTHY/BURNED/MAINTENANCE
  capacity        int,
  used_devices    int DEFAULT 0,
  x_ui_api_url    text,
  last_health_check timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- CODE_ATTEMPTS (anti-abuse)
code_attempts (
  id         bigserial PRIMARY KEY,
  tg_id      bigint,
  input      text,
  success    bool NOT NULL,
  ip_hash    text,
  ts         timestamptz NOT NULL DEFAULT now()
);

-- PAYMENTS (опционально, если потом добавим встроенные платежи)
payments (
  id          uuid PRIMARY KEY,
  user_id     bigint REFERENCES users(tg_id),
  provider    text,
  amount      numeric(10,2),
  currency    text,
  status      text,
  external_id text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- REFERRALS
referrals (
  referrer_id          bigint REFERENCES users(tg_id),
  referred_id          bigint REFERENCES users(tg_id),
  bonus_days_granted   int DEFAULT 0,
  created_at           timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (referrer_id, referred_id)
);

-- AUDIT
audit_log (
  id          bigserial PRIMARY KEY,
  admin_id    int REFERENCES admins(id),
  action      text NOT NULL,
  target_type text,
  target_id   text,
  payload     jsonb,
  ts          timestamptz NOT NULL DEFAULT now()
);

-- RU routing list (кастом)
ru_routing_list (
  id         bigserial PRIMARY KEY,
  type       text NOT NULL,                          -- domain/ip/geosite
  value      text NOT NULL,
  category   text,                                   -- banks/govt/ecom/...
  source     text,                                   -- upstream/manual
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

---

## 13. Инструкции для пользователя (по платформам)

В боте раздел **«Подключить устройство»** → выбор ОС → готовая инструкция с deep-link (одно нажатие).

### 13.1. iOS / iPadOS
- Приложения: **Hiddify** / **Streisand** / **v2RayTun** (App Store).
- Deep-link: `hiddify://install-config?url=<sub-url>` или `streisand://import/<sub-url>`.
- Альтернатива: открыть → `+` → «Импорт из URL».

### 13.2. Android
- **Hiddify-Android** (GitHub/RuStore) / **Happ** / **v2rayNG** + **NekoBox**.
- Deep-link: `hiddify://...` / `v2rayng://install-sub?url=...`.
- Альтернатива: QR-код.

### 13.3. Windows
- **Hiddify-Desktop** / **Nekoray** / **v2rayN**.
- Скачать → «Подписки» → добавить URL.

### 13.4. macOS
- **Hiddify-Desktop** / **FoXray** (App Store) / **V2Box**.
- Deep-link / импорт URL.

### 13.5. Linux
- **Hiddify-Desktop** (AppImage) / **Nekoray** (Qt) / CLI: `xray run -c config.json`.

### 13.6. TV (Android TV)
- **v2rayNG TV** / **Hiddify TV** (sideload через ADB), пошаговая инструкция.

### 13.7. Роутеры (Keenetic / OpenWRT / Mikrotik)
- Раздел **«Эксперт»**: установка `xray-core` через Entware, конфиг для всей домашней сети.

**Для каждой платформы:** скриншоты + видео 30 сек + QR-код + deep-link.

---

## 14. Безопасность бэкенда (чек-лист)

- [ ] HTTPS везде (Caddy + Let's Encrypt auto).
- [ ] Rate-limit (Redis + slowapi) на все эндпоинты бота и API.
- [ ] Валидация всех входных данных (Pydantic v2 / Zod на фронте).
- [ ] Bot token и API-ключи — через **sops+age** (никаких `.env` в репо).
- [ ] Регулярные бэкапы БД (1/час, 7 дней rolling + 30 дней weekly) на S3 (encrypted).
- [ ] Penetration test (OWASP ZAP) перед запуском.
- [ ] DDoS-protection через Cloudflare на API.
- [ ] Dependabot / Renovate — регулярное обновление зависимостей.
- [ ] 2FA (TOTP) + IP-allowlist на админке.
- [ ] Webhook Telegram — через Cloudflare с `secret_token`.
- [ ] fernet/libsodium-шифрование `codes.code`, `devices.xray_uuid` в БД (расшифровка только при выдаче).
- [ ] Логи без IP-пользователя (только hash).

---

## 15. Roadmap (этапы)

| Этап | Срок | Содержимое |
|---|---|---|
| **MVP-0** | Day 1 | Scaffold монорепо, docker-compose.dev, pre-commit, CI |
| **MVP-1** | Неделя 1 | Бот (`/start`, триал, активация кода, FSM), БД+миграции, API |
| **MVP-2** | Неделя 1.5 | Node provisioning (Ansible): Xray+Reality+Hysteria2, AGH, Nginx, nftables, fwknop, BBR |
| **MVP-3** | Неделя 2 | Админ-панель (React): коды (CRUD, batch, clone, extend, revoke), дашборд, ноды |
| **MVP-4** | Неделя 2.5 | Telegram Mini-App: Home/Devices/Instructions/Stats/Settings, полная Spotify-dark |
| **v1.0-a** | Неделя 3 | Smart-routing (singbox/mihomo JSON), AdBlock, auto-pull RU-списков |
| **v1.0-b** | Неделя 3.5 | Monitoring (Prometheus/Loki/Grafana), Probe-RU, авто-ротация IP, Uptime-Kuma |
| **v1.1** | Неделя 6+ | Реферальная, геймификация, A/B-тесты рассылок, AI-analytics churn |

---

## 16. Критерии приёмки (Definition of Done)

- [ ] `/start` → триал выдаётся за <3 сек; 1 триал на `tg_user_id` + fingerprint (дубль блокируется).
- [ ] Ввод корректного кода активирует подписку с параметрами из админки.
- [ ] Revoke кода в админке → отключение пользователя в Remnawave за <60 сек.
- [ ] Xray Reality на FI-ноде проходит `xray-knife test`, `nmap --script tls-*` не детектит VPN.
- [ ] **XHTTP H3 и H2 inbound'ы работают**, клиенты Hiddify/v2rayTun подключаются автоматически; 24-часовой флоу-тест из РФ — стабильность без блокировок (против Vision, где ТСПУ может палить длинные сессии).
- [ ] При блокировке FI-IP — авто-ротация запасного IP, активная подписка продолжает работать без ручных действий юзера.
- [ ] Smart-режим: `sber.ru` идёт direct (проверка по IP), `youtube.com` через FI.
- [ ] AdBlock: блокируется ≥95% rules из EasyList sample.
- [ ] **MTProto-прокси:** deep-link `tg://proxy?...` подключается в Telegram в один клик, работает; rotate секрета в админке → новый deep-link рассылается всем активным юзерам.
- [ ] **Домен:** все поддомены (`api`, `sub`, `app`, `admin`, `status`, `fi-01`, `mtp`) отвечают корректно; Cloudflare Access защищает `admin.`; `fi-01.` отдаёт валидный LE-сертификат и фасад-лендинг.
- [ ] Скорость: ≥600 Mbps single-stream, ≥900 Mbps multi-stream (iperf3 с гигабитной машины).
- [ ] Mini-App pixel-perfect соответствует `Design.txt` (visual QA по скриншотам).
- [ ] Админка покрывает все пункты §5.
- [ ] Тесты: ≥80% покрытие unit (pytest/vitest) + e2e-сценарии (Playwright для webapp, scripted для бота).
- [ ] Документация: `README.md`, `ARCHITECTURE.md` (Mermaid), `DEPLOY.md`, `RUNBOOK.md`.
- [ ] Один скрипт `make deploy-node HOST=fi-01.example.com` разворачивает ноду под ключ.
- [ ] Видео-демо 5 минут с прохождением всех пользовательских сценариев.

---

## 17. Структура репозитория (монорепо)

```
/bot             — aiogram 3 (Python 3.12)
/api             — FastAPI backend (Python 3.12)
/webapp          — Telegram Mini-App (React + Vite + TS)
/admin           — Admin panel (React + Vite + TS)
/panel           — docker-compose Remnawave control-plane
/node            — docker-compose для FI-ноды (Xray + AGH + Nginx + ...)
/infra           — Terraform (hosting API) + Ansible (provisioning)
/docs            — ARCHITECTURE.md, DEPLOY.md, RUNBOOK.md, plan-stage-N.md
/Design.txt      — дизайн-система (Spotify-dark, предоставлен заказчиком)
/TZ.md           — этот документ
/PROMPT.md       — мастер-промт для ИИ-разработчика
/Makefile        — make deploy-node HOST=...
```

---

## 18. Дополнительные рекомендации «свыше ТЗ»

1. **Открытый статус-сайт** (`status.<brand>.com`) с аптаймом нод — повышает доверие.
2. **Публичный Telegram-канал** с новостями — органический рост.
3. **Партнёрка с тг-каналами** через тот же реферальный механизм.
4. **Возврат денег 7 дней** без вопросов — увеличивает конверсию из триала.
5. **Tor-bridge bonus** — опциональный obfs4-bridge для гиков.
6. **DNS-only тариф** — для тех, кому нужен только анблок (через DoH/DoT с маршрутизацией), без полного VPN.
7. **Нейтральный бренд** — имя и логотип без политической окраски, помогает в App Store.
8. **Собственный стикер-пак** с маскотом (лиса/енот «обходящий стену»).
9. **Cloudflare Workers** в качестве прокси для subscription URL — легко ротируется домен, защищает от блокировок control-plane.
10. **Миграционный скрипт** для пользователей на случай полной смены хостера.

---

## 19. Risk register (что может пойти не так)

| Риск | Митигация |
|---|---|
| Reality+Vision на длинных флоу палится ТСПУ (flow-pattern detection, 2025+) | **XHTTP H3/H2** как основные inbound'ы; Vision оставлен только для legacy-совместимости |
| FI-IP заблокирован ТСПУ | Авто-ротация, резервные IP, Hysteria2 UDP как fallback |
| Reality-прикрытие (microsoft.com) попадает под DPI | Ротация списка прикрытий (apple/cloudflare/discord), A/B выбор |
| Хостер банит за спам/VPN | Aeza/PQ — лояльны; Hetzner опасен, держать в запасе |
| Утечка кодов / БД | Шифрование в БД, audit-log, TOTP+IP allowlist на админке |
| Абуз триалов (фейк-аккаунты) | Fingerprint по phone-hash, возраст аккаунта >30 дней, rate-limit |
| Падение control-plane | Cloudflare перед API, бэкапы Borg ежечасно, IaC-восстановление <30 мин |
| Закон РФ о запрете VPN | Нейтральный бренд, никаких упоминаний политики, app store-safe имя |
| Скачок нагрузки | Auto-scaling через Terraform, multi-node сразу после MVP |

---

**Конец ТЗ v1.2.**





