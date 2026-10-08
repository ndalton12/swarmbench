# lb2-protocol

Protocol definitions for the LB2 line bus (TX-40 / TX-44 sensor heads, GW-2 gateway).
Shared between the head firmware and the gateway; both pull this in as a submodule.

## Layout

- `config/lb2_spec.yaml` - PHY / symbol parameters (owned by HW systems, don't change without IM)
- `protocol/commands.csv` - opcode table incl. the 12-bit symbol for every opcode
- `protocol/frame_format.md` - frame layout
- `src/` - encode/decode + CRC, compiled into both firmwares
- `src/lb2_cmd_table.h` - generated, run `make codes`
- `tools/` - generators and helpers

## Symbols

Every opcode is send as a 12-bit symbol. Rules are in `config/lb2_spec.yaml`
(`symbols:` section). Symbols that are already deployed on rev A/B heads can
never chage - old heads in the field would stop understanding them.

## Generating symbols

    python tools/gen_cmd_codes.py 17 > /tmp/syms.txt

Python 2.7 (build server). The output is in opcode
order; paste it into commands.csv.

## Tests

    make test   (unittest)

## Contacts

H. Saathoff
