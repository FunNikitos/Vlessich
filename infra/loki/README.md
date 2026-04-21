# Loki + promtail — log aggregation (Stage 7)

Single-binary Loki for staging / single-host prod; promtail ships
structlog JSON from our compose services. Not wired into
`docker-compose.dev.yml` (local dev doesn't need a log store), deploy
as a separate stack alongside Prometheus + Grafana.

## Files

| File | Purpose |
|---|---|
| `loki-config.yml`     | Loki single-binary config (tsdb, filesystem storage, 7d retention). |
| `promtail-config.yml` | Promtail scrape config: Docker SD + JSON pipeline + level label. |

## Deploy

Suggested compose snippet (outside this repo):

```yaml
services:
  loki:
    image: grafana/loki:3.1.0
    command: ["-config.file=/etc/loki/loki-config.yml"]
    volumes:
      - ./infra/loki/loki-config.yml:/etc/loki/loki-config.yml:ro
      - loki-data:/loki
    ports: ["3100:3100"]

  promtail:
    image: grafana/promtail:3.1.0
    command: ["-config.file=/etc/promtail/promtail-config.yml"]
    volumes:
      - ./infra/loki/promtail-config.yml:/etc/promtail/promtail-config.yml:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - promtail-positions:/tmp
    depends_on: [loki]

volumes:
  loki-data: {}
  promtail-positions: {}
```

Override `external_labels.env` per environment (`dev` / `staging` / `prod`).

## Label contract

All logs are emitted by structlog as JSON (see `api/app/logging.py`,
bot / prober share the same config). Promtail promotes:

- `service` — docker-compose service (`api`, `reminders`, `prober`,
  `bot`).
- `level`   — structlog level (`debug`, `info`, `warning`, `error`).
- `logger`  — structlog logger name (e.g. `prober`, `admin.auth`).
- `env`     — static, set in `external_labels`.

## Sample LogQL queries

```logql
# All prober BURN/RECOVER events:
{service="prober", logger="prober"} |= "node_burned" or "node_recovered"

# Admin captcha failures by outcome:
{service="api"} |= "admin.login" | json | result="captcha_fail"

# Error volume by service (5m):
sum by (service) (count_over_time({level="error"}[5m]))
```

## PII / privacy

No raw IPs in logs — API hashes them via `sha256(ip + IP_SALT)` before
logging (see `app/logging.py`). Do **not** add PII via promtail
`pipeline_stages` — labels must stay PII-free.
