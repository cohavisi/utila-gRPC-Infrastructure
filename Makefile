PYTHON ?= python3

.PHONY: check
check:
	terraform fmt -check -recursive
	@for stack in state platform routing; do \
		terraform -chdir=terraform/$$stack init -backend=false -input=false -no-color >/dev/null && \
		terraform -chdir=terraform/$$stack validate -no-color || exit 1; \
	done
	terraform -chdir=terraform/platform test -no-color
	terraform -chdir=terraform/routing test -no-color
	$(PYTHON) -m unittest discover -s scripts -p 'test_*.py'
	$(PYTHON) scripts/check_manifests.py --renderer both
