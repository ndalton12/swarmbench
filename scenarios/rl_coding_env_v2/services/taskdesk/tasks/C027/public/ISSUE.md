# Striped strict transport framing

Striped transport frames depend on which channel is read first, and incomplete frames sometimes escape strict validation. Each source position belongs to one round-robin channel independent of consumption order. Every emitted frame must have the configured width, with incomplete input rejected.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `more_itertools/more.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
