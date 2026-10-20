# C011: Administrative resource descriptions

Administrative descriptions add suffixes to uncountable resource names and omit identity words from compound labels. A description joins the plural resource components into one sentence-style label without losing the identity of any component or its acronym boundaries.

Related functions: underscore, pluralize, humanize. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
