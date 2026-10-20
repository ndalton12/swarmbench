# C021: Lookahead-based rolling reader

Rolling readers behave differently after requesting a preview. Previewing must not remove input from the reader’s later windows, and windows represent consecutive positions in the original stream. Long and short previews should preserve the same underlying input.

Related functions: sliding_window, peekn. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
