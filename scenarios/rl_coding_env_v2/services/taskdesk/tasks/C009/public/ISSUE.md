# Search-result title rendering

Search results show internal name boundaries and lose words after localization. A rendered title should keep the complete field identity while producing readable title-cased words and supported ASCII approximations. Existing compound names and embedded identity words are valid inputs.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `inflection/__init__.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
