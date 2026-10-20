# Stepped windows of telemetry changes

Telemetry windows show reversed changes and sometimes create frames with no source anchor or too little padding. Changes preserve the first reading and then measure current minus previous. Windows are anchored in that change stream, with only the necessary final padding.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `more_itertools/more.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
