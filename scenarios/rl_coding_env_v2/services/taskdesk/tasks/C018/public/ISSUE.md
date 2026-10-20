# Delimited batch archive writer

Batch archives omit their first frame and mishandle the last partial frame. The archive contains every frame in order, with one boundary record only between frames. No input item may vanish because the batch size does not divide the input length.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `toolz/itertoolz.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
