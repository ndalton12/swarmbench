# distribute: behavior regression

Round-robin distribution repeats the first child stream in every bucket. Each input position belongs to exactly one child based on its position modulo n. Preserve child order and uneven lengths.

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
