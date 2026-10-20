# Feature-pair enumeration from scalar or list input

Feature-pair exports split single text labels into characters and reuse feature positions. A scalar text label is one feature; an explicit list contains its listed features. Combinations preserve input order and may use duplicate values only when distinct input positions supply them.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `more_itertools/more.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
