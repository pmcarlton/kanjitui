PYTHON ?= python3
DATA_DIR ?= data/raw
DB_PATH ?= data/db.sqlite

.PHONY: fetch-data build-db test run

fetch-data:
	bash scripts/fetch_data.sh "$(DATA_DIR)"

build-db:
	$(PYTHON) -m kanjitui --build --data-dir "$(DATA_DIR)" --db "$(DB_PATH)"

test:
	$(PYTHON) -m pytest

run:
	$(PYTHON) -m kanjitui --db "$(DB_PATH)"
