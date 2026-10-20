# C009: Search-result title rendering

Search results show internal name boundaries and lose words after localization. A rendered title should keep the complete field identity while producing readable title-cased words and supported ASCII approximations. Existing compound names and embedded identity words are valid inputs.

Related functions: titleize, humanize, transliterate. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
