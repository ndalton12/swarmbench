# Changelog

## 2.1.0 - rev B
- SET_ADDR, DIAG_ECHO, GET_TEMP, SET_UNITS, READ_ERRLOG (0x0C-0x10)
- decode: single bit correction (FW-877)
- spec_rev 3: max_edge_run 2 written into the spec (spec said 3, generator always used 2). Back-to-back runs of 5+ lost resync on long cable runs at Wendt, FW-902

## 2.0.0 - rev A
- first LB2 release, opcodes 0x00-0x0B
- symbols from tools/gen_cmd_codes.py (HS)

## 1.x
- LB1 (8-bit symbols), see old repo
