# padded: behavior regression

Padding truncates input longer than n. n is a minimum length, not a maximum; return all original items and add fill values only if necessary. Keep next_multiple behavior intact.

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
