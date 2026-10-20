# C003: Ranked archive route generation

Archive entries disagree between their visible rank and their URL. Negative positions must retain their sign, including teen positions, and the URL must retain the rank words with literal dot separators. The route is derived from the displayed rank, not a separate numbering system.

Related functions: ordinal, ordinalize, parameterize. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
