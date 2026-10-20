# Lookahead-based rolling reader

Rolling readers behave differently after requesting a preview. Previewing must not remove input from the reader’s later windows, and windows represent consecutive positions in the original stream. Long and short previews should preserve the same underlying input.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `toolz/itertoolz.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
