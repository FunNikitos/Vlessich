# =============================================================================
# Vlessich — root Makefile
# =============================================================================
# Удобные шорткаты для частых операций.
# =============================================================================

ANSIBLE_DIR := ansible
INVENTORY   := $(ANSIBLE_DIR)/inventory/hosts.yml
HOST        ?= fi-01

.PHONY: help
help:  ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'

# -- Infrastructure (Cloudflare) ---------------------------------------------

.PHONY: tf-plan tf-apply tf-destroy
tf-plan:  ## Terraform plan для Cloudflare
	cd infra && sops -d terraform.tfvars.enc > terraform.tfvars && terraform plan; rm -f terraform.tfvars

tf-apply:  ## Terraform apply (с подтверждением)
	cd infra && sops -d terraform.tfvars.enc > terraform.tfvars && terraform apply; rm -f terraform.tfvars

# -- Node provisioning -------------------------------------------------------

.PHONY: deploy-node deploy-node-update rotate-mtg-secret refresh-blocklists
deploy-node:  ## Полный provisioning ноды: make deploy-node HOST=fi-01
	ansible-playbook -i $(INVENTORY) $(ANSIBLE_DIR)/site.yml \
	  --limit $(HOST) --ask-vault-pass

deploy-node-update:  ## Обновить только Xray + Caddy + nftables
	ansible-playbook -i $(INVENTORY) $(ANSIBLE_DIR)/site.yml \
	  --limit $(HOST) --tags xray,caddy,nftables --ask-vault-pass

rotate-mtg-secret:  ## Ротировать MTProto секрет: make rotate-mtg-secret HOST=mtp
	ansible $(HOST) -i $(INVENTORY) -m shell -a "rm -f /opt/mtg/secret.txt"
	ansible-playbook -i $(INVENTORY) $(ANSIBLE_DIR)/site.yml \
	  --limit $(HOST) --tags mtg -e mtg_enabled=true --ask-vault-pass
	@echo "После деплоя — рассылка нового deep-link юзерам через бот (см. админ-панель)."

refresh-blocklists:  ## Обновить AGH/nftables списки: make refresh-blocklists HOST=fi-01
	ansible $(HOST) -i $(INVENTORY) -m shell -a "docker exec adguardhome /opt/adguardhome/AdGuardHome --check-config"

# -- Dev environment ---------------------------------------------------------

.PHONY: up down logs
up:  ## Поднять docker-compose.dev (Postgres+Redis+Mailhog)
	docker compose -f docker-compose.dev.yml up -d

down:  ## Остановить dev-окружение
	docker compose -f docker-compose.dev.yml down

logs:  ## Логи dev-окружения
	docker compose -f docker-compose.dev.yml logs -f --tail=100

# -- Test / lint -------------------------------------------------------------

.PHONY: test lint typecheck
test:  ## Прогнать pytest + vitest
	cd bot && pytest
	cd api && pytest
	cd webapp && pnpm test
	cd admin && pnpm test

lint:  ## Линтеры (ruff + eslint + prettier)
	cd bot && ruff check . && ruff format --check .
	cd api && ruff check . && ruff format --check .
	cd webapp && pnpm lint
	cd admin && pnpm lint

typecheck:  ## mypy + tsc
	cd bot && mypy --strict .
	cd api && mypy --strict .
	cd webapp && pnpm tsc --noEmit
	cd admin && pnpm tsc --noEmit
