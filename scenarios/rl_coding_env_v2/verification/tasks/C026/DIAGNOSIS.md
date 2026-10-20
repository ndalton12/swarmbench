# C026: Preview and trailing-history reconciliation

The history view no longer reconciles its preview, received count and recent items. Requesting a preview must not alter the delivered stream. The received count covers that full stream, and the recent view contains its last requested items rather than its beginning.

Related functions: peekn, tail. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
