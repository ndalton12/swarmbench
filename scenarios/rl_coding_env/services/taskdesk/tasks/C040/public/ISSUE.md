# distinct_combinations: behavior regression

Distinct combinations reuse an input position and generate impossible repeated values. Advance strictly past the selected position, while preserving legitimate duplicate values at distinct positions and deterministic order.

Keep the pinned library's other documented behavior and public API unchanged.
Allowed patch path: `more_itertools/more.py`. Changes should implement library behavior within
that source file; acceptance fixtures and test configuration are maintained separately.
Public tests are useful regressions, but do not cover every issue case.

Run the included local checks with:

```sh
python -m unittest discover -s tests -v
```

Additional upstream tests are retained under `upstream_tests/`. Some use pytest;
the local command above and acceptance checks use only the Python standard library.
Documentation examples remain in the library's docstrings and README.rst.
