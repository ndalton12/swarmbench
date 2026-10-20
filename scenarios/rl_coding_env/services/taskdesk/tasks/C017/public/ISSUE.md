# get: behavior regression

Selecting a single index using a list of indices drops the tuple shape. List-index requests always return a tuple, including empty and singleton selections. Scalar indexing and defaults retain their existing behavior.

Keep the pinned library's other documented behavior and public API unchanged.
Allowed patch path: `toolz/itertoolz.py`. Changes should implement library behavior within
that source file; acceptance fixtures and test configuration are maintained separately.
Public tests are useful regressions, but do not cover every issue case.

Run the included local checks with:

```sh
python -m unittest discover -s tests -v
```

Additional upstream tests are retained under `upstream_tests/`. Some use pytest;
the local command above and acceptance checks use only the Python standard library.
Documentation examples remain in the library's docstrings and README.rst.
