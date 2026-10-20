# C019: Case-insensitive frequency summary

Frequency summaries report one occurrence for repeated words and emit the same logical word more than once. Counts are case-insensitive across the full input; the exported summary retains the first spelling and first-seen order of each word.

Related functions: frequencies, unique. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
