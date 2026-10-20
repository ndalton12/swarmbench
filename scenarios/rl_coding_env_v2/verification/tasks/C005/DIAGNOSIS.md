# C005: Localized catalog labels and slugs

Localized catalog fields lose letters in their labels and collapse to empty or shortened slugs. Both outputs should retain ASCII approximations of supported accented text, retain embedded identifier words, and agree on the field being represented. Slugs use literal plus separators.

Related functions: parameterize, transliterate, humanize. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
