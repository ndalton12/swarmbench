# Weighted outer-join account ledger

The weighted account ledger duplicates matched entries, drops first contributions, and mixes audit rows between accounts. Totals and audit membership must describe the same outer join: unmatched entries retain unit weight, missing entries contribute zero, and every account gets its own audit list.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `toolz/itertoolz.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
