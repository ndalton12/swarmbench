# Signed report section links

Links to signed report sections have started pointing to different sections. Every underscore in the section identifier belongs to the section path, the rank retains its sign, and punctuation between the section and rank is represented by a literal plus separator. Existing section components must not disappear.

The integration in `workflow.py` reproduces the affected caller. Repair the library
so the integration and other documented public behavior work correctly.
Allowed patch path: `inflection/__init__.py`. Acceptance fixtures and test configuration
are maintained separately. The included examples cover only part of the contract.

Run `python -m unittest discover -s tests -v` to reproduce the local examples.
Additional upstream tests are retained in `upstream_tests/`; some require pytest.
The library README and function docstrings describe its public API.
