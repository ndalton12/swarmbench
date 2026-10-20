# HBX interface, extract from the billing handover

One ASCII record per line, LF line endings. Fields are fixed width. Spaces are
significant. The writer is a per-record transformation: neither file name, batch
position nor neighbouring rows changes a record. IDs can repeat on retries; they
are source sequence numbers, not a unique database key. Reordering a batch only
reorders the output. Reference batches were frozen from the 2024 ledger extract.

Positions (one based):

| Columns | Field | Notes |
| --- | --- | --- |
| 1-3 | record code | SHP, MNF, RTN, CNS, INV, CLM |
| 4-9 | source sequence | id, six decimal digits, zero-filled |
| 10-17 | account | eight characters |
| 18-26 | local stamp | YYDDDhhmm, Europe/London; DDD starts at 001 |
| 27-30 | origin | outward postcode, uppercase, space-padded |
| 31-34 | destination | outward postcode, uppercase, space-padded |
| 35-40 | packed weight | decagrams, six decimal digits |
| 41-43 | pieces | three decimal digits |
| 44 | dispatch mode | S standard, X express, E economy; depot extension exists |
| 45-54 | amount | sign followed by nine decimal pence digits |
| 55-72 | customer reference | uppercase ASCII, 18 characters |
| 73-74 | TRG | tariff region, see region-notes.md |
| 75-78 | detail | record-specific, space-padded |
| 79 | check digit | see xconv/writer.py, reconciled with SHP |

Uppercase before stripping characters outside ASCII, then truncate before padding.
Weight rounding is nearest decagram, halves upwards. Do not use binary floats
for that rounding. A summer UTC timestamp can fall on the next local day.
The common writer handles these cases already. Keep its completed types working.

SHP amount is declared value; MNF amount is zero. Both carry the depot in detail.
The four remaining type mappings are on their tickets. Some old desk codes were
not in the type sheet; compare the supplied sample captures before submitting.
