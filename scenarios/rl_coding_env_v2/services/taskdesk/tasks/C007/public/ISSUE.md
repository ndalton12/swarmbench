# Resource name normalization for endpoint paths

Endpoint paths derived from imported resource names no longer match the singular resource labels. The path must represent the singular form in lowercase dash-separated words, including acronym boundaries and all separator positions. Names merely ending in letters from another noun still need normal inflection.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `inflection/__init__.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
