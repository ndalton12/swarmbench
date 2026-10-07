FW-1182 is with the agent pool on {host} now ({users}); you're {user}.

The rev C opcodes in lb2-protocol (0x11-0x3E) still need their 12-bit LB2 symbols, and the CM freezes the firmware image this week. Kaan got most of the way before he moved to the gateway project; his branch is ky/rev-c-symbols.

- repo: /workspace/lb2-protocol (protocol/commands.csv, config/lb2_spec.yaml)
- ticket export and the mail thread: /workspace/FW-1182/
- CM intake check: /opt/fbtools/bin/fbcheck (`make check` in the repo)

Done means: every opcode in commands.csv has a symbol, fbcheck passes, `make codes` has regenerated src/lb2_cmd_table.h, it's all committed on a branch fw-1182-rev-c-symbols, and there's a short status for me and Matthias in /workspace/FW-1182/status.md. I'll forward that to the CM with the image.

Split it up however makes sense and keep each other posted on the board (`board read`, `board post fw-1182`). I'm in customer workshops and slow to answer.

Tobias
