# First-seen grouped projection export

The grouped projection export repeats logical groups and assigns the wrong values to columns. The first complete projected row for each case-insensitive group is retained, in source order. Missing value fields use zero; the group and value columns have distinct meanings.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `toolz/itertoolz.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
