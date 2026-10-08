# One command for each step. CI runs the same targets.
# Every target runs inside the uv environment, so no global installs are needed.

PKG := household_credit_stress
RUN := uv run
DOCS := README.md CLAIMS.md CHANGELOG.md $(wildcard MODEL_CARD.md DATASHEET.md) docs

.PHONY: setup lint test eval demo check-docs all

setup:
	uv sync

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .
	$(RUN) mypy

test:
	$(RUN) pytest

eval:
	$(RUN) python -m $(PKG).evaluate

demo:
	$(RUN) python -m $(PKG).demo

check-docs:
	$(RUN) python tools/writing_style_check.py $(DOCS)
	$(RUN) python tools/claims_check.py $(DOCS)
	$(RUN) python tools/readability_check.py --glossary docs/glossary.md $(DOCS)
	$(RUN) python tools/links_check.py $(DOCS)
	$(RUN) python tools/readme_sections.py check README.md
	$(RUN) python tools/readme_sections.py repo-map README.md --check

all: setup lint test eval demo check-docs
