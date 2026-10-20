# C001: Schema registry names and display labels

The schema registry now publishes identifiers containing separators and its display labels lose parts of their names. The key and label describe the same field: identifiers must use lower camel case, while labels keep embedded identifier words and omit only a trailing metadata suffix. Acronyms in existing schema names still need ordinary word boundaries.

Related functions: camelize, underscore, humanize. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
