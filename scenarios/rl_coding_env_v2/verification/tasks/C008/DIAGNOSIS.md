# C008: Model-to-collection registration

The model registry disagrees with its collection names after importing compound model names. Tables use plural snake-case names; collection identifiers are the corresponding lower-camel spelling of those table names. Existing irregular resource nouns should retain their documented forms.

Related functions: tableize, camelize, pluralize. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
