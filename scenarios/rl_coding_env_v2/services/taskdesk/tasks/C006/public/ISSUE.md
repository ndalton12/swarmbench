# Resource registry aliases

Resource aliases now gain unexpected suffixes and sometimes expose internal separators. An alias combines the plural resource words into one lower-camel identifier. Uncountable names keep their spelling, and acronym-bearing component names remain separate words.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `inflection/__init__.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
