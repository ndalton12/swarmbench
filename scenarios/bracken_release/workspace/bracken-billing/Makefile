PYTHON ?= python3

.PHONY: export verify packet clean
export:
	$(PYTHON) tools/export_invoices.py --input data/intake_sample.csv --policy config/export_policy.json --out out/current

verify: export
	$(PYTHON) -m unittest discover -s tests
	$(PYTHON) tools/reconcile.py --source data/intake_sample.csv --export out/current/invoices.csv --rejected out/current/rejected.csv

packet: verify
	mkdir -p delivery
	cp out/current/invoices.csv delivery/invoices.csv
	cp out/current/rejected.csv delivery/rejected.csv
	$(PYTHON) tools/reconcile.py --source data/intake_sample.csv --export delivery/invoices.csv --rejected delivery/rejected.csv > delivery/reconciliation.txt

clean:
	rm -rf out/current
