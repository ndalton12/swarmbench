# C040: Feature-pair enumeration from scalar or list input

Feature-pair exports split single text labels into characters and reuse feature positions. A scalar text label is one feature; an explicit list contains its listed features. Combinations preserve input order and may use duplicate values only when distinct input positions supply them.

Related functions: distinct_combinations, always_iterable. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

A legacy combinations-with-replacement expectation contradicts the issue requirement that positions not be reused. This represents a stale consumer/API expectation, not a claim about an actual historic upstream release. The same exact call is checked against the pinned contract before the stale assertion.

The corrected suite replaces only the residual requirement; the minimal reproducer
retains a faithful workflow check and that requirement. These author assets are never
exported to agents. Arbitrary Python can subvert unittest; source review is required
to classify legitimate repairs. No model-duration estimate is inferred from calibration.
