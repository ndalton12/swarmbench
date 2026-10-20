# Database migration filename generation

Generated migration filenames no longer match their target table names. A filename is the dash-separated spelling of the plural snake-case table name, including all words in compound acronym-bearing model names. Different naming surfaces must identify the same table.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `inflection/__init__.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
