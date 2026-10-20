# Scalar-or-list field redaction

Field redaction behaves differently for one text field and a list of fields, loses neighboring fields, and exceeds the replacement limit. Text is one field unless explicitly supplied as a list. Replacements preserve all nonmatching fields and stop at the requested count.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `more_itertools/more.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
