# C012: Database migration filename generation

Generated migration filenames no longer match their target table names. A filename is the dash-separated spelling of the plural snake-case table name, including all words in compound acronym-bearing model names. Different naming surfaces must identify the same table.

Related functions: dasherize, tableize, underscore. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
