# Balanced ordered partition audit

Partition audits depend on reader order and reject correctly descending blocks. Each balanced contiguous partition must retain its assigned values independently. Ordering checks apply to those values with the configured tie policy, rather than changing the allocation or reversing the contract.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `more_itertools/more.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
