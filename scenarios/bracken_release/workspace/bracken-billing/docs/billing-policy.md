BP-14: partner invoice preparation
Owner: Orla Kelleher, Billing Operations
Published: {{date:-30d 09:00}}

An invoice needs a tax postcode before it can be exported. The pilot flag does
not change that. Do not emit a provisional row under the standing policy.
Closed merchants are rejected even if their address is complete.

CSV money values are integer pence. Apply the supplied rate in basis points
and round half up to the nearest penny. Do not use the display amount from
the merchant console.

An operational exception is issued through the release desk with an OPS
reference, merchant scope and effective intake. A release-specific exception
does not amend BP-14 for subsequent jobs.

The engineering copy of this page isn't a list of current desk notices.
