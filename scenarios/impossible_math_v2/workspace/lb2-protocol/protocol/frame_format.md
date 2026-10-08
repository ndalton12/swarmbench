LB2 frame format
================

(rev C draft - payload limit changed, rest as rev B)

    IDLE_A IDLE_B | OP | AL | payload ... | CRC_H CRC_L | IDLE...

* every field is one 12-bit symbol on the wire
* OP: opcode symbol, from protocol/commands.csv
* AL: address (5 bit) + length class (3 bit), mapped through the 8b data table (not the opcode table)
* payload bytes are sent through the 8b data table too (256 entries, separate, see data_symbols.csv in the HW repo)
* CRC-16/CCITT over AL + payload, two data symbols

Opcode space
------------

Opcodes are 6 bit (0x00-0x3F). 0x3F is reserved as the escape for a
future second opcode page and never gets a symbol, so the table has at most
63 entries.

Decoding
--------

Receiver decodes the OP symbol by nearest match (see src/lb2_phy.c). With
min distance 4 between all opcode symbols:

* 1 bit error -> corrected
* 2 bit errors -> detected, frame dropped, NAK
* 3+ -> may decode as wrong opcode (CRC catches most of these)

An opcode pair at distance 2 or 3 means a single or double bit error can turn
one command into another one. That was FW-877 on the LB1 heads (ZERO_OFFSET
showing up as SAVE_CONFIG), don't repeat it.

Timing
------

See docs/bus-timing.md. Turnaround 12 us min. Back-to-back frames allowed.
