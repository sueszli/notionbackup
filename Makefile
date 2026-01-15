.PHONY: lint # statically analyze code
lint:
	uvx ruff check .
	uv run --with deal==4.24.6 --with beautifulsoup4==4.12.3 --with click==8.1.7 --with tqdm==4.66.4 pyright .
	uv run --with deal==4.24.6 python3 -m deal lint notionbackup.py
	uv run --with deal==4.24.6 python3 -m deal test notionbackup.py

.PHONY: fmt # format code
fmt:
	uvx isort .
	uvx autoflake --remove-all-unused-imports --recursive --in-place .
	uvx black --line-length 5000 .

.PHONY: e2e-test # run end-to-end tests
e2e-test:
	uv run notionbackup.py ./test-data/all-blocks.zip
	uv run notionbackup.py ./test-data/blog.zip
	uv run notionbackup.py ./test-data/full-templates.zip

.PHONY: help # show all available commands
help:
	@echo "Usage: make \033[1;32m<target>\033[0m"
	@echo ""
	@echo "Available targets:"
	@grep -E '^\.PHONY: [a-zA-Z0-9_-]+ #' $(MAKEFILE_LIST) | sed 's/\.PHONY: //' | awk 'BEGIN {FS = " # "}; {printf "  \033[1;32m%-18s\033[0m %s\n", $$1, $$2}'
