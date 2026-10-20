Export field notes

id is the old source sequence. account is the ledger account, not a depot ID.
created retains its original UTC offset. Weight is a decimal string in kilograms.
reference is free text copied from the handheld. Undocumented extra JSON fields
are permitted in the export but should not appear in HBX.

Return fields: return_reason, original_ref.
Consignment fields: depot, vehicle.
Invoice fields: invoice_no, net_pence, vat_pence.
Claim fields: claim_reason, claim_amount_pence.

Column inventory from the CSV-to-JSON move is recorded under tickets/archive.
