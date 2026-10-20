# First-record reconciliation join

Reconciliation emits repeated logical entries and marks already matched entries as unmatched. The first input row for each key is authoritative. It participates in every legitimate lookup match, while only keys absent from the lookup receive a missing-partner record.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `toolz/itertoolz.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
