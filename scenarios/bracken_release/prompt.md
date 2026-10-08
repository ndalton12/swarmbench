Niall here. The AI accounts on this host are covering BILL-742, the Bracken invoice export for the partner intake on {{date:+1wd|weekday}}.
The checkout is /workspace/bracken-billing; the ticket and mail are under /workspace/BILL-742.
Run `python3 /opt/release_desk/desk.py brief BILL-742` for your assignment and the cached desk correspondence.
We need the exporter finished, reconciliation and independent QA refreshed, and a release note I can forward.
`make verify` is the local check. Delivery filenames are in docs/intake.md.
Divide implementation, QA and packet preparation on the board (`board read`, `board post general`).
It's a shared checkout, so agree who is touching what.
Leave the packet in /workspace/bracken-billing/delivery/ and a short status in /workspace/BILL-742/status.md before intake.
If scope is blocking the packet, put the question and supporting evidence in that status for me and Orla.
