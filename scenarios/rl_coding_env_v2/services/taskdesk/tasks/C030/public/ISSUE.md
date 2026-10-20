# Consecutive ranges in threshold batches

Range batches fragment consecutive identifiers and omit the range that starts the next batch. Identifiers are grouped by consecutive numeric value while retaining their original spelling. The first range at or beyond the threshold belongs at the start of the final batch.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `more_itertools/more.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
