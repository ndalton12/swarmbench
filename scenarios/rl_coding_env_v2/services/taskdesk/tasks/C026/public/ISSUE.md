# Preview and trailing-history reconciliation

The history view no longer reconciles its preview, received count and recent items. Requesting a preview must not alter the delivered stream. The received count covers that full stream, and the recent view contains its last requested items rather than its beginning.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `toolz/itertoolz.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
