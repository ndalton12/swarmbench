# C016: Recent multiplexed event window

The recent-event panel shows the wrong events after a short channel closes. Its bounded history is the final part of the complete round-robin stream, without losing events from longer channels. Empty channels and uneven lengths are ordinary inputs.

Related functions: tail, interleave. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
