# Ordered channel validation

Channel validation reports the wrong data and ordering status when readers run in a different order. Each round-robin channel has stable ownership of its source positions. Its descending-order flag must reflect that channel’s values, including the configured policy on ties.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `more_itertools/more.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
