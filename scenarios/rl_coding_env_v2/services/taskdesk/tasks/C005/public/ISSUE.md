# Localized catalog labels and slugs

Localized catalog fields lose letters in their labels and collapse to empty or shortened slugs. Both outputs should retain ASCII approximations of supported accented text, retain embedded identifier words, and agree on the field being represented. Slugs use literal plus separators.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `inflection/__init__.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
