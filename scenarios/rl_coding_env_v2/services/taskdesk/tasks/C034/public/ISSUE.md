# Balanced block window export

Block-window exports assign records to the wrong block and produce malformed final windows. Balanced contiguous blocks must be independent readers. Windows belong to each block’s own records and retain the required padding without adding source-free windows.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `more_itertools/more.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
