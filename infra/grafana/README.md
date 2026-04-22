# Grafana / Prometheus wiring

Grafana не запускается в `docker-compose.dev.yml` (локально избыточно).
В staging / prod поднимайте как отдельный стек. Ниже — минимальная
конфигурация для scrape обоих источников.

## Prometheus scrape config

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: vlessich-api
    metrics_path: /metrics
    static_configs:
      - targets: ['api:8000']

  - job_name: vlessich-prober
    metrics_path: /metrics
    static_configs:
      - targets: ['prober:9101']

  - job_name: vlessich-mtg
    metrics_path: /metrics
    static_configs:
      - targets: ['mtg:9410']
```

## Dashboard

Импортируйте `dashboards/vlessich.json` через Grafana UI
(Dashboards → Import → Upload JSON). Datasource variable
`DS_PROMETHEUS` нужно привязать к существующему Prometheus-источнику.

Панели:

1. **HTTP RPS by route** — `rate(vlessich_http_request_duration_seconds_count)`.
2. **HTTP p95 latency by route** — `histogram_quantile(0.95, …)`.
3. **Admin login outcomes** — `rate(vlessich_admin_login_total)` по
   label `result`.
4. **Probe success ratio** — `ok/total` по `vlessich_probe_total`.
5. **Node states** — instant `vlessich_node_state == 1` в виде table.
6. **Subscription events** — `rate(vlessich_subscription_events_total)`
   по label `event`.

## Alert rules (Stage 7)

См. `infra/prometheus/rules/vlessich.yml`. Подключить через
`prometheus.yml`:

```yaml
rule_files:
  - /etc/prometheus/rules/vlessich.yml
```

Alerts: `NodeBurnSpike`, `ProbeSuccessLow` (only `source="edge"`),
`ProberDown`, `ApiP95Latency`, `AdminCaptchaFailSpike`.
Alertmanager wiring — deploy-time, не в этом репо.
