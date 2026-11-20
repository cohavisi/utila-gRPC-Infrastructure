PYTHON ?= python3

.PHONY: check install-hooks
check:
	terraform fmt -check -recursive
	@for stack in state platform routing; do \
		terraform -chdir=terraform/$$stack init -backend=false -input=false -no-color >/dev/null && \
		terraform -chdir=terraform/$$stack validate -no-color || exit 1; \
	done
	terraform -chdir=terraform/platform test -no-color
	terraform -chdir=terraform/routing test -no-color
	$(PYTHON) -m coverage run --source=scripts --omit='scripts/test_*.py' -m unittest discover -s scripts -p 'test_*.py'
	$(PYTHON) -m coverage report --show-missing
	$(PYTHON) scripts/check_manifests.py

install-hooks:
	git config --local core.hooksPath .githooks
