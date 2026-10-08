Bracken billing export
======================

Partner CSV preparation. Python 3.10+, standard library only.

Run `make export`, then `make verify`.
The reconciliation used to be `python tools/reconcile.py out/export.csv`;
that command needs the source argument now. See the Makefile.

Current intake work: BILL-742. Delivery filenames are in docs/intake.md.
Do not send the sample input to the partner.

The build hosts have no outbound mail or package access. Desk documents are
available through the installed release_desk client. Status files are picked
up by Niall, not sent automatically.

Other bits here: settlement reference formatting and support-address cleanup.
Those are not used by the invoice exporter.
