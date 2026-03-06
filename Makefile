PYTHON ?= python3
DATA_DIR ?= data/raw
DB_PATH ?= data/db.sqlite

.PHONY: fetch-data build-sentences build-db build-web-docs package-macos test release-smoke run run-gui

fetch-data:
	bash scripts/fetch_data.sh "$(DATA_DIR)"

build-sentences:
	PYTHONPATH=src $(PYTHON) scripts/build_sentences.py --download-dir "$(DATA_DIR)/tatoeba" --out "$(DATA_DIR)/sentences.tsv"

build-db:
	$(PYTHON) -m kanjitui --build --data-dir "$(DATA_DIR)" --db "$(DB_PATH)"

build-web-docs:
	mkdocs build -d web/landing/docs

package-macos:
	bash scripts/package_macos.sh

test:
	$(PYTHON) -m pytest

release-smoke:
	bash scripts/release_smoke.sh

run:
	$(PYTHON) -m kanjitui --db "$(DB_PATH)"

run-gui:
	$(PYTHON) -m kanjitui.gui.main --db "$(DB_PATH)"
