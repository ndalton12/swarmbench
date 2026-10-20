# Redacted token window transport

Token transport drops content after a redacted pair and emits malformed windows at stream boundaries. Redaction replaces non-overlapping private/value pairs up to the configured limit. Windows then cover the resulting stream, preserving remaining tokens and only the required final padding.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `more_itertools/more.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
