# Committed journal page construction

Committed journal pages repeat a commit token and occasionally accept an incomplete page. The commit token closes the first segment and appears only there. Each segment is divided into complete pages; an incomplete segment must be rejected instead of silently producing a short page.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `more_itertools/more.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
