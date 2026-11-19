.PHONY: precommit
precommit:
	$(MAKE) precommit-hook
	$(MAKE) fmt
	$(MAKE) lint
	$(MAKE) tests

.PHONY: precommit-hook
precommit-hook:
	@common_dir="$$(git rev-parse --git-common-dir 2>/dev/null)"; \
	hooks_path="$$(git config --get core.hooksPath 2>/dev/null)"; \
	hook="$$common_dir/hooks/pre-push"; \
	if [ -n "$$common_dir" ] && [ -z "$$hooks_path" ] && [ ! -e "$$hook" ] && [ ! -L "$$hook" ]; then \
	mkdir -p "$$common_dir/hooks" && printf '#!/bin/sh\nmake precommit\n' > "$$hook" && chmod +x "$$hook"; \
	fi

.PHONY: fmt
fmt:
	uvx ruff check --fix --line-length 5000 --target-version py314 --extend-select I --ignore E731 notionbackup.py
	uvx ruff format --line-length 5000 --target-version py314 notionbackup.py

.PHONY: lint
lint:
	uvx vulture --min-confidence 80 notionbackup.py
	uv run --with pyright --with-requirements notionbackup.py pyright notionbackup.py

.PHONY: tests
tests:
	rm -rf /tmp/notionbackup && mkdir /tmp/notionbackup && cp test-data/*.zip /tmp/notionbackup
	for z in /tmp/notionbackup/*.zip; do uv run notionbackup.py "$$z" || exit 1; done
