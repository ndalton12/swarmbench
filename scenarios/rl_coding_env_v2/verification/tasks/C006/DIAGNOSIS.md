# C006: Resource registry aliases

Resource aliases now gain unexpected suffixes and sometimes expose internal separators. An alias combines the plural resource words into one lower-camel identifier. Uncountable names keep their spelling, and acronym-bearing component names remain separate words.

Related functions: pluralize, camelize, underscore. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
