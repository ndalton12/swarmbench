# Case-insensitive frequency summary

Frequency summaries report one occurrence for repeated words and emit the same logical word more than once. Counts are case-insensitive across the full input; the exported summary retains the first spelling and first-seen order of each word.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `toolz/itertoolz.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
