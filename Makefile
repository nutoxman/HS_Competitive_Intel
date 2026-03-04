VENV=.venv
PYTHON=$(VENV)/bin/python
STREAMLIT=$(VENV)/bin/streamlit
PYTEST=$(VENV)/bin/pytest
HS_SOURCE_CONFIG?=data/source_configs/sponsor_sources.json
HS_DECK_ROOT?=data/pipeline_decks
HS_ROLLING_YEARS?=5
HS_HARVEST_SOURCE_CONFIG?=data/source_configs/sponsor_sources.comprehensive.json

run:
	$(STREAMLIT) run ui/app.py

run-hs:
	$(STREAMLIT) run ui/hs_tracker_app.py

hs-refresh-ctgov:
	$(PYTHON) -m hs_tracker.jobs.run_ctgov_refresh --rolling-years $(HS_ROLLING_YEARS)

hs-scan-sources:
	$(PYTHON) -m hs_tracker.jobs.run_source_scan --config $(HS_SOURCE_CONFIG)

hs-scan-decks:
	$(PYTHON) -m hs_tracker.jobs.run_deck_scan --deck-root $(HS_DECK_ROOT)

hs-harvest-decks:
	$(PYTHON) -m hs_tracker.jobs.harvest_investor_decks --deck-root $(HS_DECK_ROOT) --source-config $(HS_HARVEST_SOURCE_CONFIG)

hs-ingest-all:
	$(PYTHON) -m hs_tracker.jobs.run_all_ingestion --rolling-years $(HS_ROLLING_YEARS) --source-config $(HS_SOURCE_CONFIG) --deck-root $(HS_DECK_ROOT)

test:
	$(PYTEST)
