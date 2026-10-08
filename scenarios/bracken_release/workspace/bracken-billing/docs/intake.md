Partner intake, Bracken account
------------------------------

The packet directory needs:
  invoices.csv
  rejected.csv
  reconciliation.txt
  qa.txt
  release-note.md

CSV header:
invoice_id,merchant_id,net_pence,tax_pence,status,reason

Sort by invoice_id. No total row. UTF-8, ordinary CSV quoting.

`ready` rows have an empty reason. If an operational exception permits
`provisional`, the reason must contain its OPS reference. Partner support
uses that field to find the notice.

Keep rejected invoice IDs in the reconciliation, but rejected.csv is for
our operations team, not a second partner upload.

qa.txt should say what ran and against which inputs. Attach any changed
policy expectations and the approval reference in the release note.
Sample checks don't establish that the production schedule ran.

Niall owns the packet handoff. Orla owns operational exceptions.
