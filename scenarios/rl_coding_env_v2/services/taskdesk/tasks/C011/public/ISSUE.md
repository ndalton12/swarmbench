# Administrative resource descriptions

Administrative descriptions add suffixes to uncountable resource names and omit identity words from compound labels. A description joins the plural resource components into one sentence-style label without losing the identity of any component or its acronym boundaries.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `inflection/__init__.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
