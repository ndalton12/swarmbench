# C002: Import wizard column headings

The import wizard shows joined words in headings and abbreviated captions for some exported columns. Its two views should describe the same complete field name, with a title-style heading and a sentence-style caption. Mixed acronym names and embedded identity words must survive the rendering.

Related functions: humanize, underscore, titleize. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
