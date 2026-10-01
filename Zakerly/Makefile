# KFH Knowledge Assistant - control the app with `make <target>` (run `make` for the list).
#
# The app is the docker compose stack in this folder (docker-compose.yml + docker-compose.override.yml).
# The LLM is NOT part of the stack: it is the host's vLLM container (gemma4-gb10-vllm, from ~/gemma-gb10)
# on port 8000. `make up` checks it and starts it if needed.

.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE     := docker compose
GEMMA       := gemma4-gb10-vllm
GEMMA_NET   := gemma-gb10_default
LLM_URL     := http://localhost:8000/v1/models
APP_URL     := http://localhost:3001
HOST_IP     := $(shell hostname -I | awk '{print $$1}')
TS_IP       := $(shell ip -4 -o addr show tailscale0 2>/dev/null | awk '{print $$4}' | cut -d/ -f1)
# Owner of the demo data: app user email, from DEMO_OWNER in .env (or `make demo-load OWNER=you@example.com`)
OWNER       ?= $(shell grep -E '^DEMO_OWNER=' .env 2>/dev/null | cut -d= -f2-)

.PHONY: help up down start stop restart build rebuild ps status logs logs-% clean \
        llm-up llm-status health urls demo-load demo-test demo-reset db-backup check-env

help:
	@echo "KFH Knowledge Assistant"
	@echo ""
	@echo "App"
	@echo "  make up            Start everything (checks/starts the Gemma LLM first)"
	@echo "  make down          Stop and remove the app containers (data is kept)"
	@echo "  make start | stop  Start / stop existing containers"
	@echo "  make restart       Restart the app containers"
	@echo "  make build         Build images (after code changes)"
	@echo "  make rebuild       Rebuild images without cache and restart"
	@echo "  make ps            Container status"
	@echo "  make status        Containers + LLM + service health + URLs"
	@echo "  make logs          Follow all logs   |  make logs-<service>  e.g. make logs-chat-service"
	@echo "  make urls          Print the URLs to open"
	@echo ""
	@echo "LLM (host vLLM, Gemma 4)"
	@echo "  make llm-up        Start Gemma if stopped, repair its network, wait until it answers"
	@echo "  make llm-status    Is Gemma answering on port 8000?"
	@echo ""
	@echo "Demo data (demo/manifest.json + demo/documents/)"
	@echo "  make demo-load     Create the demo knowledge bases and upload the documents (owner: DEMO_OWNER)"
	@echo "  make demo-test     Ask the demo questions and check each answer cites sources"
	@echo "  make demo-reset    Delete the demo knowledge bases, documents and embeddings"
	@echo ""
	@echo "Data"
	@echo "  make db-backup     Dump the database to backups/zakerly-<timestamp>.sql.gz"
	@echo "  make clean         Remove containers AND volumes (deletes all data; asks first)"

# ---------------------------------------------------------------- app

check-env:
	@test -f .env || { echo "Missing .env - copy .env.example to .env and fill it in"; exit 1; }

up: check-env llm-up
	$(COMPOSE) up -d
	@$(MAKE) --no-print-directory urls

down:
	$(COMPOSE) down

start: llm-up
	$(COMPOSE) start

stop:
	$(COMPOSE) stop

restart:
	$(COMPOSE) restart

build: check-env
	$(COMPOSE) build

rebuild: check-env
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d

ps:
	@$(COMPOSE) ps --format 'table {{.Name}}\t{{.Status}}\t{{.Ports}}'

status: ps llm-status health urls

logs:
	$(COMPOSE) logs -f --tail=100

logs-%:
	$(COMPOSE) logs -f --tail=200 $*

health:
	@echo "Services (through the frontend proxy):"
	@curl -sf -m 5 $(APP_URL)/api/v1/status | python3 -c 'import json,sys; d=json.load(sys.stdin); \
		print("  gateway: " + d.get("gateway","?")); [print(f"  {k}: {v}") for k,v in d.get("services",{}).items()]' \
		|| echo "  not reachable - is the app up? (make up)"

urls:
	@echo ""
	@echo "Open the app:"
	@echo "  this machine  $(APP_URL)"
	@echo "  LAN           http://$(HOST_IP):3001"
	@if [ -n "$(TS_IP)" ]; then echo "  Tailscale     http://$(TS_IP):3001"; fi
	@echo "  pgAdmin       http://$(HOST_IP):8081"

# ---------------------------------------------------------------- LLM

llm-up:
	@if ! docker inspect $(GEMMA) >/dev/null 2>&1; then \
		echo "LLM container $(GEMMA) not found - set LLM_BASE_URL in docker-compose.override.yml to your LLM"; exit 1; fi
	@if [ "$$(docker inspect -f '{{.State.Running}}' $(GEMMA))" != "true" ]; then \
		echo "Starting $(GEMMA)..."; docker start $(GEMMA) >/dev/null; fi
	@# The container can come up "healthy" with no network (and no port 8000) if its network was recreated
	@if [ "$$(docker inspect -f '{{len .NetworkSettings.Networks}}' $(GEMMA))" = "0" ]; then \
		echo "Reattaching $(GEMMA) to $(GEMMA_NET)"; docker network connect $(GEMMA_NET) $(GEMMA); fi
	@echo -n "Waiting for Gemma on port 8000 (first start loads the model, up to ~10 min)"; \
	for i in $$(seq 1 120); do curl -sf -m 3 $(LLM_URL) >/dev/null && { echo " - ready"; exit 0; }; echo -n "."; sleep 5; done; \
	echo " - not ready, check: docker logs --tail 50 $(GEMMA)"; exit 1

llm-status:
	@if curl -sf -m 3 $(LLM_URL) >/dev/null; then echo "LLM: Gemma answering on port 8000"; \
	elif docker inspect $(GEMMA) >/dev/null 2>&1; then echo "LLM: NOT answering (container $$(docker inspect -f '{{.State.Status}}' $(GEMMA))) - run make llm-up"; \
	else echo "LLM: $(GEMMA) not found"; fi

# ---------------------------------------------------------------- demo data

demo-load:
	@test -n "$(OWNER)" || { echo "Set DEMO_OWNER=<app user email> in .env, or run: make demo-load OWNER=you@example.com"; exit 1; }
	python3 demo/demo.py load --owner "$(OWNER)"

demo-test:
	@test -n "$(OWNER)" || { echo "Set DEMO_OWNER=<app user email> in .env, or run: make demo-test OWNER=you@example.com"; exit 1; }
	python3 demo/demo.py test --owner "$(OWNER)"

demo-reset:
	@read -p "Delete the demo knowledge bases and their documents? [y/N] " a && [ "$$a" = y ]
	python3 demo/demo.py reset

# ---------------------------------------------------------------- data

db-backup:
	@mkdir -p backups
	docker exec zakerly_postgres pg_dump -U zakerly_user zakerly_db | gzip > backups/zakerly-$$(date +%Y%m%d-%H%M%S).sql.gz
	@ls -lh backups | tail -1

clean:
	@read -p "This deletes ALL app data (users, documents, embeddings, models). Continue? [y/N] " a && [ "$$a" = y ]
	$(COMPOSE) down -v
