# Ranked archive route generation

Archive entries disagree between their visible rank and their URL. Negative positions must retain their sign, including teen positions, and the URL must retain the rank words with literal dot separators. The route is derived from the displayed rank, not a separate numbering system.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `inflection/__init__.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
