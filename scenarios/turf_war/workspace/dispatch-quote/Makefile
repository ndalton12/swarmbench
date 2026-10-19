.PHONY: serve check test
serve:
	sh scripts/serve.sh

check:
	python3 /opt/dispatch_checks/check.py

test:
	python3 -m unittest discover -s tests -v
