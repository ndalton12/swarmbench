# C035: Scalar-or-list field redaction

Field redaction behaves differently for one text field and a list of fields, loses neighboring fields, and exceeds the replacement limit. Text is one field unless explicitly supplied as a list. Replacements preserve all nonmatching fields and stop at the requested count.

Related functions: always_iterable, replace. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
