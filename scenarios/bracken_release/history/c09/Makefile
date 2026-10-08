PYTHON ?= python3

export:
	$(PYTHON) tools/export_invoices.py --input data/intake_sample.csv --policy config/export_policy.json --out out/current

verify: export
	$(PYTHON) -m unittest discover -s tests
