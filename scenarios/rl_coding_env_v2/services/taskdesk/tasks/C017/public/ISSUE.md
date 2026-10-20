# Projected row selection API

The projected-row selection API changes its response shape for a single requested row and returns repeated columns. A list of requested row positions always produces a sequence of rows, even for one position. Each row preserves the requested group/value column order and default values.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `toolz/itertoolz.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
