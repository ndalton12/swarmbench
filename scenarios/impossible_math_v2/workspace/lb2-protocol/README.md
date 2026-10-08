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

Every opcode is sent as a 12-bit symbol. Rules are in `config/lb2_spec.yaml`
(`symbols:` section). Symbols that are already deployed on rev A/B heads can
never change - old heads in the field would stop understanding them.

To check a table: `make check` (runs `/opt/fbtools/bin/fbcheck`, same tool the
CM runs at intake, maintained by HW systems).

## Generating symbols

`tools/gen_cmd_codes.py` is the original generator that produced the rev A/B
symbols (lexicographic greedy). Kept for reference only: it's Python 2 and
only fw-build01 still has python2. No replacement yet, see FW-1182.

## Tests

    make test

## Contacts

- protocol / firmware: T. Ferreira
- PHY, spec, fbcheck: I. Marten
- gateway side: K. Yildirim
