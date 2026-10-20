# Import wizard column headings

The import wizard shows joined words in headings and abbreviated captions for some exported columns. Its two views should describe the same complete field name, with a title-style heading and a sentence-style caption. Mixed acronym names and embedded identity words must survive the rendering.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `inflection/__init__.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
