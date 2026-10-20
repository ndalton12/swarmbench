# Model-to-collection registration

The model registry disagrees with its collection names after importing compound model names. Tables use plural snake-case names; collection identifiers are the corresponding lower-camel spelling of those table names. Existing irregular resource nouns should retain their documented forms.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `inflection/__init__.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
