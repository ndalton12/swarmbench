# Multiplexed transport frames

Transport frames reorder or lose events when channels end at different times. Channels contribute in round-robin order while active, and frames retain the entire merged stream, including a final partial frame. An exhausted channel must not discard another channel’s remaining events.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `toolz/itertoolz.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
