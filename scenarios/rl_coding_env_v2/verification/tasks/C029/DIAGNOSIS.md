# C029: Escaped-delimiter record splitting

The record splitter loses text after escaped delimiters and reintroduces delimiters into the unsplit remainder. Escaped comma pairs become literal comma tokens; the first remaining comma separates records and is excluded. Later commas remain ordinary content in the unsplit tail.

Related functions: split_at, replace. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
