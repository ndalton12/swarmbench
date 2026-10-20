# Escaped-delimiter record splitting

The record splitter loses text after escaped delimiters and reintroduces delimiters into the unsplit remainder. Escaped comma pairs become literal comma tokens; the first remaining comma separates records and is excluded. Later commas remain ordinary content in the unsplit tail.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `more_itertools/more.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
