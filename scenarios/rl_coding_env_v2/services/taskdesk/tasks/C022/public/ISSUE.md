# Previewed batch delivery

Batch delivery loses previewed records and trims partial frames. A preview is informational; delivery must still include every original record exactly once, in order, with the last frame allowed to be shorter. Preview length and frame size are independent settings.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `toolz/itertoolz.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
