# Change-series ordering audit

Change-series audits disagree with the original readings and their ordering verdict. The first reading is retained, later values measure current minus previous, and the audit checks whether those changes are descending under the configured tie policy. Values and verdict must describe the same series.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `more_itertools/more.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
