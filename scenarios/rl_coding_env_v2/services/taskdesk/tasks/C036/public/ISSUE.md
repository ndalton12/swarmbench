# Range batches with a closing range

Range batches lose grouping and repeat their closing range in the following batch. Numeric adjacency determines each range, preserving original labels. The first range meeting the size threshold closes its batch and must not appear again in the remainder.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `more_itertools/more.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
