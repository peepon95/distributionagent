PYTHON := .venv/bin/python

.PHONY: setup ingest ingest-all ingest-reddit test enrich index update dev

setup:
	python3 -m venv .venv
	$(PYTHON) -m pip install -U pip
	$(PYTHON) -m pip install -r requirements.txt

# Usage: make ingest CHANNEL=@starterstory [LIMIT=3]
ingest:
	$(PYTHON) -m pipeline.ingest_youtube $(CHANNEL) $(if $(LIMIT),--limit $(LIMIT))

ingest-all:
	$(PYTHON) -m pipeline.ingest_youtube @SuperwallHQ
	$(PYTHON) -m pipeline.ingest_youtube @starterstory
	$(PYTHON) -m pipeline.ingest_web

# Usage: make ingest-reddit [LIMIT=5]
ingest-reddit:
	$(PYTHON) -m pipeline.ingest_reddit $(if $(LIMIT),--limit $(LIMIT))

test:
	$(PYTHON) -m pytest tests/ -q

enrich:
	$(PYTHON) -m pipeline.enrich $(if $(BUDGET),--budget $(BUDGET))

index:
	$(PYTHON) -m pipeline.index

update:
	$(PYTHON) -m pipeline.update $(ARGS)

search:
	$(PYTHON) -m pipeline.search "$(Q)"

dev:
	cd web && npm run dev
