# Recent multiplexed event window

The recent-event panel shows the wrong events after a short channel closes. Its bounded history is the final part of the complete round-robin stream, without losing events from longer channels. Empty channels and uneven lengths are ordinary inputs.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `toolz/itertoolz.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
