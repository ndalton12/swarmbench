# C015: Multiplexed transport frames

Transport frames reorder or lose events when channels end at different times. Channels contribute in round-robin order while active, and frames retain the entire merged stream, including a final partial frame. An exhausted channel must not discard another channel’s remaining events.

Related functions: interleave, partition_all. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
