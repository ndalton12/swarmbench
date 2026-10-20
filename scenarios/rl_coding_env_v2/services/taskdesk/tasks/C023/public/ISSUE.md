# Projected group totals and membership

Group exports disagree between their projected rows, totals and membership lists. Projection must keep distinct field values, every row contributes once to its group total, and membership lists remain independent even when groups are interleaved in the source.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `toolz/itertoolz.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
