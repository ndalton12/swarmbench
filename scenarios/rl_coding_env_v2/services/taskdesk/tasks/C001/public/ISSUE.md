# Schema registry names and display labels

The schema registry now publishes identifiers containing separators and its display labels lose parts of their names. The key and label describe the same field: identifiers must use lower camel case, while labels keep embedded identifier words and omit only a trailing metadata suffix. Acronyms in existing schema names still need ordinary word boundaries.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `inflection/__init__.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
